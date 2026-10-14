#!/usr/bin/env python3
"""Restore three established metadata fields without changing any other data.

The source is the published ds003745 2.1.1 metadata, restored in the code
repository's dataset_description.json. This creates at most one regular-text
Git blob/commit and pushes main only. No annex transfers or snapshot creation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://openneuro.org/git/0/ds003745"
FIELDS = ("EthicsApprovals", "Acknowledgements", "Authors")
FILE = "dataset_description.json"
SOURCE = "https://github.com/OpenNeuroDatasets/ds003745/blob/2.1.1/dataset_description.json"


def git(repo, *args, data=None, index=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return subprocess.check_output(["git", "-C", str(repo), *map(str, args)],
                                   input=data, text=True, env=env).strip()


def encode(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def correction(current, restored, historical):
    result = dict(current)
    for field in FIELDS:
        old, new = current.get(field), restored[field]
        accepted = [historical.get(field), new]
        if field == "EthicsApprovals":
            accepted.extend(["n/a", ["n/a"], [], ["Temple IRB #24452 "]])
        if old not in accepted:
            raise ValueError(f"{field} was independently edited; stop for review rather than overwrite")
        result[field] = new
    assert {k: v for k, v in result.items() if k not in FIELDS} == {
        k: v for k, v in current.items() if k not in FIELDS}
    return result


def make_commit(repo, base, content, work):
    # Isolated index: never reuse old annex modes or disturb the candidate's
    # working tree/index. Preserve every other path directly from remote main.
    with tempfile.TemporaryDirectory(prefix="metadata-index-", dir=work) as temporary:
        index = Path(temporary) / "index"
        git(repo, "read-tree", base, index=index)
        blob = git(repo, "hash-object", "-w", "--stdin", data=content)
        git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{FILE}", index=index)
        tree = git(repo, "write-tree", index=index)
        if git(repo, "diff", "--name-only", "--no-renames", base, tree) != FILE:
            raise ValueError("metadata commit does not change exactly dataset_description.json")
        if not git(repo, "ls-tree", tree, "--", FILE).startswith("100644 blob "):
            raise ValueError("metadata must remain a regular Git file")
        return git(repo, "commit-tree", tree, "-p", base, "-m",
                   "Restore published ethics approval, acknowledgments and author names")


def head(repo):
    rows = git(repo, "ls-remote", "origin", "refs/heads/main").splitlines()
    if len(rows) != 1:
        raise ValueError("cannot identify remote main")
    return rows[0].split()[0]


def run(args):
    repo, dataset, report = args.candidate.resolve(), args.dataset_root.resolve(), args.report_dir.resolve()
    if git(repo, "remote", "get-url", "origin") != URL:
        raise ValueError("candidate origin is not ds003745 on OpenNeuro")
    if git(repo, "status", "--porcelain"):
        raise ValueError("candidate has local changes; preserve and inspect them")
    if git(repo, "ls-remote", "--tags", "origin", "refs/tags/2.2.0"):
        raise ValueError("2.2.0 is already published; do not amend it with this draft repair")
    if report.is_relative_to(dataset) or report.is_relative_to(repo):
        raise ValueError("report must be outside dataset and candidate")
    restored = json.loads((ROOT / "bids" / FILE).read_text())
    historical = json.loads(git(ROOT, "show", f"4bfc9aa:bids/{FILE}"))
    git(repo, "fetch", "origin", "main")
    base = git(repo, "rev-parse", "origin/main")
    current = json.loads(git(repo, "show", f"{base}:{FILE}"))
    updated = correction(current, restored, historical)
    local_path = dataset / FILE
    if local_path.is_symlink() or not local_path.is_file() or (dataset / ".git").exists():
        raise ValueError("dataset root must be the plain download, not an annex checkout")
    local_bytes = local_path.read_bytes()
    local = json.loads(local_bytes)
    local_update = correction(local, restored, historical)
    changed = [k for k in FIELDS if current.get(k) != updated[k]]
    print("Remote metadata fields to restore:", ", ".join(changed) or "none; already correct", flush=True)
    print("EthicsApprovals:", updated["EthicsApprovals"], flush=True)
    if not args.execute:
        print("Preview only. No local metadata, remote files or branches were changed.")
        return
    work = repo.parent / "approval-metadata-repair"
    work.mkdir(exist_ok=True)
    # Serialize this repair, including concurrent retries from separate shells.
    import fcntl
    with (work / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report.mkdir(parents=True, exist_ok=True)
        receipt = dict(source=SOURCE, base=base, changed_fields=changed,
                       image_files_transferred=0, snapshot_published=False)
        if head(repo) != base:
            raise ValueError("remote main advanced; rerun preview before proceeding")
        if changed:
            (work / f"remote-before-{base}.json").write_text(encode(current))
            commit = make_commit(repo, base, encode(updated), work)
            # Keep a recoverable local ref without changing HEAD or the worktree.
            git(repo, "update-ref", f"refs/metadata-repairs/{commit}", commit)
            receipt["commit"] = commit
            (report / "approval-repair.json").write_text(encode(dict(receipt, remote_main_verified=False)))
            git(repo, "push", "origin", f"{commit}:refs/heads/main")
        else:
            commit = base
            receipt["commit"] = commit
        if head(repo) != commit:
            raise ValueError("cannot confirm remote main equals the repaired metadata commit")
        # Also fix the plain download so later releases cannot restore the omission.
        # Back up before atomic replacement; do not overwrite unrelated local edits.
        if local_path.read_bytes() != local_bytes:
            raise ValueError("downloaded metadata changed during upload; remote repair succeeded, local sync stopped")
        if local != local_update:
            digest = hashlib.sha256(local_bytes).hexdigest()
            backup = work / f"download-before-{digest}.json"
            if backup.exists() and backup.read_bytes() != local_bytes:
                raise ValueError("unexpected existing backup content")
            backup.write_bytes(local_bytes)
            with tempfile.NamedTemporaryFile(mode="w", dir=dataset, prefix=".approval-", delete=False) as stream:
                stream.write(encode(local_update))
                temporary = Path(stream.name)
            temporary.chmod(0o644)
            os.replace(temporary, local_path)
        receipt.update(remote_main_verified=True, local_download_corrected=True)
        (report / "approval-repair.json").write_text(encode(receipt))
        print(f"PASS: metadata correction verified on OpenNeuro: {commit}")
        print("PASS: plain download synchronized; no image files transferred.")
        print("Do not rerun the consolidated uploader. Refresh the draft and review before publishing 2.2.0.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=Path("/ZPOOL/data/scratch/srndna-datapaper-openneuro-2.2.0/consolidated-v1/candidate"))
    parser.add_argument("--dataset-root", type=Path, default=Path("/ZPOOL/data/datasets/ds003745-work"))
    parser.add_argument("--report-dir", type=Path, default=ROOT / "results/openneuro_release/approval-metadata-v1")
    parser.add_argument("--execute", action="store_true")
    try:
        run(parser.parse_args())
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"STOP: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
