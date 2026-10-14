#!/usr/bin/env python3
"""Prepare, build and upload one consolidated ds003745 update, in separate stages.

Never edits the downloaded dataset or the earlier recovery repository. The new
candidate is based on the current remote main, not the malformed recovery commit.
No force pushes, snapshot tags, blanket staging, or implicit remote deletions.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from prepare_openneuro_2_2_release import make_release_plan, read_tsv, sha256
from repair_openneuro_validation import check_full_dataset, excluded_name

ROOT = Path(__file__).resolve().parents[1]
URL = "https://openneuro.org/git/0/ds003745"
BRANCH = "release-2.2.0-consolidated"
RELEASE_TOOLS = (
    "code/OPENNEURO_CONSOLIDATED_RELEASE.md", "code/finalize_openneuro_release.py",
    "code/run_openneuro_consolidated_release.sh", "code/git-annex-remote-openneuro",
    "code/prepare_openneuro_2_2_release.py", "code/repair_openneuro_validation.py",
    "code/clean_openneuro_warnings.py", "code/recover_dicom_metadata.py",
    "code/validate_openneuro_full_dataset.py", "code/summarize_bids_validation.py",
)


def run(args, cwd=None, *, capture=True, data=None, check=True):
    result = subprocess.run([str(x) for x in args], cwd=cwd, input=data,
                            stdout=subprocess.PIPE if capture else None,
                            text=True, check=check,
                            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    return result.stdout.strip() if capture and check else result


def git(repo, *args, **kwargs):
    return run(["git", "-C", repo, *args], **kwargs)


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def safe_relative(value):
    path = Path(value)
    if path.is_absolute() or not path.parts or any(p in ("..", ".git") for p in path.parts):
        raise ValueError(f"unsafe release path: {value}")
    if any(c in value for c in "\n\r\t\0"):
        raise ValueError("control character in release path")
    return path


def regular(root, relative):
    path = root / safe_relative(relative)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"expected an ordinary source file inside dataset: {path}")
    return path


def participant_check(dataset):
    ids = [r["participant_id"] for r in read_tsv(dataset / "participants.tsv")]
    primary = sorted(p.name for p in dataset.glob("sub-1*") if p.is_dir())
    auxiliary = sorted(p.name for p in dataset.glob("sub-2*") if p.is_dir())
    if len(ids) != 50 or len(set(ids)) != 50 or sorted(ids) != primary:
        raise ValueError("primary participant rows/directories are not exactly the same 50 IDs")
    if "sub-2*" not in [s.strip() for s in (dataset / ".bidsignore").read_text().splitlines()]:
        raise ValueError("auxiliary participant exclusion is missing")
    unexpected = [p.name for p in dataset.glob("sub-*") if p.is_dir() and p.name not in primary + auxiliary]
    if unexpected:
        raise ValueError(f"unclassified participant directories: {unexpected}")
    return dict(primary_participants=50, primary_rows_match_directories=True,
                ignored_auxiliary_directories=len(auxiliary), auxiliary_files_changed=0)


def make_plan(dataset, code=ROOT):
    check_full_dataset(dataset)
    participants = participant_check(dataset)
    if len(list(dataset.glob("sub-*/func/*_bold.nii.gz"))) != 418:
        raise ValueError("expected 418 retained raw BOLD images")
    files = {}
    for item in make_release_plan(code, dataset):
        rel = item.destination.as_posix()
        # Preserve the completed DICOM/validation repairs in the full download.
        source = item.source if item.category == "reproducibility" else regular(dataset, rel)
        digest = sha256(source)
        if item.expected_sha256 and digest != item.expected_sha256:
            raise ValueError(f"ratings checksum changed: {rel}")
        if item.category == "event_repair" and digest != sha256(item.source):
            raise ValueError(f"event repair differs from approved repository copy: {rel}")
        files[rel] = dict(path=rel, source=str(source), category=item.category,
                          sha256=digest, bytes=source.stat().st_size)
    for rel in RELEASE_TOOLS:
        source = regular(code, rel)
        files[rel] = dict(path=rel, source=str(source), category="release_reproducibility",
                          sha256=sha256(source), bytes=source.stat().st_size)
    cleanup = json.loads((code / "results/openneuro_validation/cleanup_v1/cleanup-manifest.json").read_text())
    images = [r for r in cleanup["files"] if r["kind"] == "gzip"]
    if len(images) != 668:
        raise ValueError("expected 668 checksum-recorded, losslessly cleaned raw images")
    for index, row in enumerate(images, 1):
        rel = row["path"]
        if not re.fullmatch(r"sub-1\d\d/(anat|func|fmap)/[^/]+\.nii\.gz", rel):
            raise ValueError(f"unexpected raw-image scope: {rel}")
        for name, kind in ((rel, "raw_gzip_header"), (rel[:-7] + ".json", "raw_metadata")):
            source = regular(dataset, name)
            digest = sha256(source)
            if kind == "raw_gzip_header" and digest != row["after"]:
                raise ValueError(f"image differs from completed lossless cleanup: {name}")
            if kind == "raw_metadata":
                metadata = json.loads(source.read_text())
                required = ("PulseSequenceType", "CoilCombinationMethod", "MatrixCoilMode", "NonlinearGradientCorrection")
                if any(k not in metadata for k in required) or metadata.get("PartialFourier") != 1:
                    raise ValueError(f"missing recovered metadata or unexpected PartialFourier: {name}")
                if "/fmap/" in name and not metadata.get("SliceTiming"):
                    raise ValueError(f"missing recovered fieldmap slice timing: {name}")
                intended = metadata.get("IntendedFor", [])
                intended = [intended] if isinstance(intended, str) else intended
                if any(excluded_name(p) for p in intended):
                    raise ValueError(f"excluded run remains in fieldmap IntendedFor: {name}")
            files[name] = dict(path=name, source=str(source), category=kind, sha256=digest, bytes=source.stat().st_size)
        if index % 50 == 0:
            print(f"Verified raw images and sidecars: {index}/668", flush=True)
    for sub in ("134", "138"):
        rel = f"sub-{sub}/sub-{sub}_scans.tsv"
        source = regular(dataset, rel)
        if any(excluded_name(Path(r["filename"]).name) for r in read_tsv(source)):
            raise ValueError(f"excluded acquisition remains in {rel}")
        files[rel] = dict(path=rel, source=str(source), category="scan_inventory", sha256=sha256(source), bytes=source.stat().st_size)
    deletions = read_tsv(code / "results/openneuro_validation/deletions.tsv")
    if len(deletions) != 48 or len({d["path"] for d in deletions}) != 48:
        raise ValueError("expected the 48 explicitly audited run-05 exclusions")
    for row in deletions:
        rel = safe_relative(row["path"])
        if not excluded_name(rel.name) or rel.as_posix() in files:
            raise ValueError(f"invalid exclusion: {rel}")
        if (dataset / rel).exists():
            raise ValueError(f"excluded file remains in complete download: {rel}")
    for rel, row in files.items():
        safe_relative(rel)
        if re.search(r"(^|/)sub-2", rel):
            raise ValueError("auxiliary subjects must not be changed")
        row["annex"] = rel.endswith(".nii.gz")
        # Explicit modes prevent the historical literal-text-as-symlink bug.
        row["mode"] = "120000" if row["annex"] else "100644"
        if not row["annex"] and (rel.endswith((".py", ".sh")) or rel.endswith("git-annex-remote-openneuro")):
            if Path(row["source"]).read_bytes().startswith(b"#!"):
                row["mode"] = "100755"
        if not row["annex"] and row["bytes"] > 1000000:
            raise ValueError(f"unexpected large text file: {rel}")
    return dict(version=1, dataset_root=str(dataset), files=list(files.values()),
                deletions=deletions, participant_audit=participants,
                code_commit=git(code, "rev-parse", "HEAD"))


def validation_summary(report, participant_audit):
    issues = report["issues"]["issues"]
    if any(i["severity"] == "error" for i in issues):
        raise ValueError("full-dataset validation has errors; no candidate may be uploaded")
    summary = report["summary"]
    subjects = set(summary["subjects"])
    metadata = {r["participantId"] for r in summary["subjectMetadata"]}
    if len(subjects) != 50 or subjects != metadata:
        raise ValueError("validator primary participant inventory does not reconcile")
    groups = collections.Counter((i["severity"], i["code"], i.get("subCode", "")) for i in issues)
    approved = {("warning", "SIDECAR_KEY_RECOMMENDED", "PartialFourierDirection"),
                ("warning", "SIDECAR_KEY_RECOMMENDED", "CogPOID"),
                ("warning", "SIDECAR_KEY_RECOMMENDED", "CogAtlasID"),
                ("warning", "PARTICIPANT_ID_MISMATCH", ""),
                ("warning", "JSON_KEY_RECOMMENDED", "HEDVersion"),
                ("warning", "JSON_KEY_RECOMMENDED", "SourceDatasets")}
    if set(groups) - approved:
        raise ValueError(f"new validation issue groups require review: {set(groups) - approved}")
    return dict(errors=0, warning_instances=sum(groups.values()),
                issues=[dict(severity=k[0], code=k[1], subcode=k[2], count=n) for k, n in sorted(groups.items())],
                **participant_audit)


def prepare(dataset, work, report_dir):
    plan_path = work / "plan.json"
    plan = make_plan(dataset)
    if plan_path.exists():
        previous = json.loads(plan_path.read_text())
        # Committing operational logs alone must not invalidate a resume.
        if {k: v for k, v in previous.items() if k != "code_commit"} != {k: v for k, v in plan.items() if k != "code_commit"}:
            raise ValueError("release inputs changed since preparation; retain this directory and use a new work root")
        plan = previous
    save(plan_path, plan)
    validation = work / "validation"
    if not (validation / "invocation.json").exists():
        run([sys.executable, ROOT / "code/validate_openneuro_full_dataset.py",
             "--dataset-root", dataset, "--output-dir", validation], capture=False)
    invocation = json.loads((validation / "invocation.json").read_text())
    if invocation.get("exit_status") != 0 or invocation["dataset_root"] != str(dataset):
        raise ValueError("validation incomplete or not for this dataset; preserve logs and inspect")
    summary = validation_summary(json.loads((validation / "validation.json").read_text()), plan["participant_audit"])
    summary.update(files=len(plan["files"]), exclusions=len(plan["deletions"]),
                   categories=dict(collections.Counter(r["category"] for r in plan["files"])),
                   annex_files=sum(r["annex"] for r in plan["files"]),
                   annex_bytes=sum(r["bytes"] for r in plan["files"] if r["annex"]))
    report_dir.mkdir(parents=True, exist_ok=True)
    save(report_dir / "preparation.json", summary)
    save(work / "prepared.json", dict(plan_sha256=sha256(plan_path)))
    print(json.dumps(summary, indent=2), flush=True)
    print("PASS: full candidate inputs checked; dataset and OpenNeuro unchanged")


def load_plan(work):
    if json.loads((work / "prepared.json").read_text())["plan_sha256"] != sha256(work / "plan.json"):
        raise ValueError("prepared plan changed")
    return json.loads((work / "plan.json").read_text())


def install_file(repo, row):
    source = Path(row["source"])
    if source.is_symlink() or sha256(source) != row["sha256"]:
        raise ValueError(f"release source changed: {source}")
    relative = safe_relative(row["path"])
    dest = repo / relative
    if not dest.parent.resolve().is_relative_to(repo.resolve()):
        raise ValueError(f"candidate parent escapes repository: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Unlink only this explicit candidate path, NEVER write through an annex link.
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    shutil.copyfile(source, dest)
    dest.chmod(0o755 if row["mode"] == "100755" else 0o644)
    if row["annex"]:
        git(repo, "annex", "add", "--backend=SHA256E", "--", relative, capture=False)
        expected = f'SHA256E-s{row["bytes"]}--{row["sha256"]}.nii.gz'
        key = git(repo, "annex", "lookupkey", "--", relative)
        if key != expected or not dest.is_symlink():
            raise ValueError(f"unexpected annex key or unlocked file: {relative}")
    else:
        oid = git(repo, "hash-object", "-w", "--no-filters", "--", relative)
        git(repo, "update-index", "--add", "--cacheinfo", f'{row["mode"]},{oid},{relative.as_posix()}')


def tree_entries(repo, ref):
    raw = git(repo, "ls-tree", "-r", "-z", ref)
    return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split() for line in raw.split("\0") if line}


def audit_tree(repo, base, ref, plan):
    entries = tree_entries(repo, ref)
    allowed = {r["path"] for r in plan["files"]} | {r["path"] for r in plan["deletions"]}
    changed = set(git(repo, "diff", "--name-only", "--no-renames", "-z", base, ref).strip("\0").split("\0")) - {""}
    if changed - allowed:
        raise ValueError(f"unexpected candidate changes: {sorted(changed - allowed)}")
    for row in plan["files"]:
        mode, kind, oid = entries[row["path"]]
        if mode != row["mode"] or kind != "blob":
            raise ValueError(f'wrong Git mode: {row["path"]}: {mode}')
        blob = subprocess.check_output(["git", "-C", str(repo), "cat-file", "blob", oid])
        if row["annex"]:
            key = f'SHA256E-s{row["bytes"]}--{row["sha256"]}.nii.gz'
            target = blob.decode()
            resolved = os.path.normpath(str(Path(row["path"]).parent / target))
            if not re.fullmatch(r"\.git/annex/objects/[^/]+/[^/]+/" + re.escape(key) + "/" + re.escape(key), resolved):
                raise ValueError(f'invalid annex symlink: {row["path"]}')
        else:
            import hashlib
            if hashlib.sha256(blob).hexdigest() != row["sha256"]:
                raise ValueError(f'candidate text checksum mismatch: {row["path"]}')
    if any(r["path"] in entries for r in plan["deletions"]):
        raise ValueError("an excluded run file remains in candidate tree")
    return sorted(changed)


def setup_candidate(work):
    repo = work / "candidate"
    state_path = work / "candidate.json"
    if state_path.exists():
        return repo, json.loads(state_path.read_text())
    initializing = work / "initializing.json"
    identity = dict(url=URL, candidate=str(repo))
    if repo.exists() and (not initializing.exists() or json.loads(initializing.read_text()) != identity):
        raise ValueError("candidate directory was not initialized by this workflow; preserve and inspect")
    cli = shutil.which("openneuro-deno")
    if not cli or not shutil.which("git-annex-remote-openneuro"):
        raise ValueError("openneuro-deno and git-annex-remote-openneuro must be on PATH")
    save(initializing, identity)
    git(work, "init", str(repo), capture=False)
    git(repo, "config", "core.symlinks", "true")
    git(repo, "config", "credential.https://openneuro.org.useHttpPath", "true")
    # Reset inherited helper lists only for this new clone, then reuse CLI login.
    git(repo, "config", "--unset-all", "credential.https://openneuro.org.helper", check=False)
    git(repo, "config", "--add", "credential.https://openneuro.org.helper", "")
    git(repo, "config", "--add", "credential.https://openneuro.org.helper", f"{shlex.quote(cli)} git-credential")
    origin = git(repo, "remote", "get-url", "origin", check=False)
    if origin.returncode:
        git(repo, "remote", "add", "origin", URL)
    elif origin.stdout.strip() != URL:
        raise ValueError("candidate initialization origin changed")
    git(repo, "fetch", "origin", "main", "git-annex", capture=False)
    base = git(repo, "rev-parse", "origin/main")
    # A reset by support should leave the published 2.1.1 commit as the base.
    # A newer remote draft needs deliberate reconciliation, not blind replacement.
    if not base.startswith("cc3fee633f"):
        raise ValueError(f"remote main is now {base}; inspect before applying the 2.1.1-based release")
    branch = git(repo, "show-ref", "--verify", f"refs/heads/{BRANCH}", check=False)
    if branch.returncode:
        git(repo, "checkout", "-b", BRANCH, "origin/main", capture=False)
    elif git(repo, "symbolic-ref", "--short", "HEAD") != BRANCH or git(repo, "rev-parse", "HEAD") != base:
        raise ValueError("candidate initialization HEAD changed")
    git(repo, "annex", "init", "ds003745 consolidated 2.2.0 release", capture=False)
    git(repo, "config", "annex.addunlocked", "false")
    state = dict(base=base)
    save(state_path, state)
    return repo, state


def build(work, report_dir):
    plan = load_plan(work)
    if not (work / "candidate").exists():
        needed = sum(r["bytes"] for r in plan["files"]) + 1024 ** 3
        if shutil.disk_usage(work).free < needed:
            raise ValueError(f"candidate requires at least {needed / 1024 ** 3:.1f} GiB free")
    repo, state = setup_candidate(work)
    if not state.get("commit"):
        if git(repo, "rev-parse", "HEAD") != state["base"]:
            raise ValueError("candidate HEAD changed outside this workflow")
        for n, row in enumerate(plan["files"], 1):
            install_file(repo, row)
            if n % 25 == 0:
                print(f"Installed candidate files: {n}/{len(plan['files'])}", flush=True)
        for row in plan["deletions"]:
            rel = safe_relative(row["path"])
            dest = repo / rel
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            git(repo, "update-index", "--force-remove", "--", rel)
        tree = git(repo, "write-tree")
        audit_tree(repo, state["base"], tree, plan)
        # commit-tree makes the exact audited parent/tree explicit; no hooks or
        # blanket add can silently change this release. Old recovery is untouched.
        commit = git(repo, "commit-tree", tree, "-p", state["base"],
                     "-m", "Release corrected events, single-trial estimates, ratings and metadata")
        save(work / "candidate.json", dict(state, commit=commit))
        git(repo, "update-ref", f"refs/heads/{BRANCH}", commit, state["base"])
        state["commit"] = commit
    # Recover the narrow interruption between checkpoint and branch update.
    head = git(repo, "rev-parse", "HEAD")
    if head == state["base"]:
        git(repo, "update-ref", f"refs/heads/{BRANCH}", state["commit"], state["base"])
    elif head != state["commit"]:
        raise ValueError("candidate HEAD is not the recorded release")
    changed = audit_tree(repo, state["base"], state["commit"], plan)
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("candidate working tree is not clean; inspect, do not reset")
    report_dir.mkdir(parents=True, exist_ok=True)
    save(report_dir / "candidate.json", dict(state, changed_files=len(changed),
          changed_paths=changed, explicit_exclusions=[r["path"] for r in plan["deletions"]],
          git_modes_and_checksums_verified=True, uploaded=False))
    print(f"PASS: clean candidate {state['commit']}; {len(changed)} changed paths; nothing uploaded")


def remote_head(repo):
    lines = git(repo, "ls-remote", "origin", "refs/heads/main").splitlines()
    if len(lines) != 1:
        raise ValueError("cannot resolve OpenNeuro main")
    return lines[0].split()[0]


def upload(work, report_dir):
    plan = load_plan(work)
    build(work, report_dir)
    repo = work / "candidate"
    state = json.loads((work / "candidate.json").read_text())
    if git(repo, "remote", "get-url", "origin") != URL:
        raise ValueError("candidate origin changed")
    if remote_head(repo) not in (state["base"], state["commit"]):
        raise ValueError("remote main changed; stop for reconciliation, never force-push")
    # Native git-annex protocol, as documented by OpenNeuro. The helper reuses
    # the existing CLI login. Initialization only changes this new local clone.
    enabled = git(repo, "config", "--get", "remote.openneuro.annex-uuid", check=False)
    if enabled.returncode != 0:
        attempt = git(repo, "annex", "enableremote", "openneuro", f"url={URL}", check=False, capture=False)
        if attempt.returncode:
            git(repo, "annex", "initremote", "openneuro", "type=external", "externaltype=openneuro",
                "encryption=none", f"url={URL}", capture=False)
    objects = [r for r in plan["files"] if r["annex"]]
    verified = 0
    for row in objects:
        key = f'SHA256E-s{row["bytes"]}--{row["sha256"]}.nii.gz'
        for attempt in range(3):
            check = git(repo, "annex", "checkpresentkey", key, "openneuro", check=False, capture=False)
            if check.returncode == 0:
                break
            if check.returncode != 1:
                raise ValueError(f"remote presence check failed ({check.returncode}): {row['path']}")
            print(f"TRANSFER {attempt + 1}/3: {row['path']}", flush=True)
            git(repo, "annex", "transferkey", key, "--to=openneuro", "--force", capture=False)
            time.sleep(2)
        else:
            # Last transfer must be checked too, not assumed successful.
            git(repo, "annex", "checkpresentkey", key, "openneuro", capture=False)
        verified += 1
        print(f"Remote objects verified: {verified}/{len(objects)}", flush=True)
    git(repo, "fetch", "origin", "main", "git-annex", capture=False)
    if remote_head(repo) not in (state["base"], state["commit"]):
        raise ValueError("remote main advanced during transfer; no main push attempted")
    git(repo, "annex", "merge", capture=False)
    git(repo, "merge-base", "--is-ancestor", "origin/git-annex", "git-annex")
    git(repo, "push", "origin", "git-annex:git-annex", capture=False)
    if remote_head(repo) != state["commit"]:
        git(repo, "push", "origin", f"{state['commit']}:refs/heads/main", capture=False)
    if remote_head(repo) != state["commit"]:
        raise ValueError("remote main does not match candidate after push")
    save(report_dir / "upload.json", dict(state, remote_main_verified=True,
         verified_annex_files=verified, snapshot_published=False))
    print("PASS: OpenNeuro main matches the candidate. Review remote validation, then publish 2.2.0 in the UI.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "build", "upload"))
    parser.add_argument("--dataset-root", type=Path, default=Path("/ZPOOL/data/datasets/ds003745-work"))
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    work, dataset, report = args.work_root.resolve(), args.dataset_root.resolve(), args.report_dir.resolve()
    try:
        if work.is_relative_to(dataset) or dataset.is_relative_to(work) or work.is_relative_to(ROOT):
            raise ValueError("work root must be separate from dataset and code repository")
        if report.is_relative_to(dataset) or report.is_relative_to(work):
            raise ValueError("public report directory must be separate from private dataset/work directories")
        work.mkdir(parents=True, exist_ok=True)
        # Lock released automatically on process termination; no stale PID guessing.
        import fcntl
        with (work / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.stage == "prepare":
                prepare(dataset, work, report)
            elif args.stage == "build":
                build(work, report)
            else:
                upload(work, report)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        parser.exit(1, f"STOP: {error}\nPreserve all directories and logs. Do not force-push or retry the old recovery commit.\n")


if __name__ == "__main__":
    raise SystemExit(main())
