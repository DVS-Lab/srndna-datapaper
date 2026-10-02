#!/usr/bin/env python3
"""Preview/apply backed-up metadata corrections and two Trust run exclusions.

Only operates on a complete, plain-files OpenNeuro download, never a Git/annex
checkout. No remote operations or image-content edits are performed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

SUBJECTS = ("134", "138")
TASKS = ("trust", "ultimatum", "sharedreward")
# 420 published raw BOLD files, minus up to the two approved exclusions.
EXPECTED_BOLD_COUNTS = {418, 419, 420}
RUN_PATTERN = re.compile(r"^sub-(134|138)_task-trust_run-0*5(?:_|\.)")
NOTE = (
    "Trust run-05 for sub-134 and sub-138 is excluded from this release, together "
    "with its run-specific derivatives, because the corresponding behavioral "
    "records are unavailable. The previous event tables were empty conversion "
    "placeholders. Retained logs uniquely match the run-01 through run-04 trial "
    "schedules; the reason for the missing fifth-run records is unknown. "
    "The 218 regenerated Trust single-trial outputs already exclude these runs."
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)
        return reader.fieldnames or [], rows


def excluded_name(value: str) -> bool:
    return bool(RUN_PATTERN.match(value.rsplit("/", 1)[-1]))


def regular(path: Path, root: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular, present file (not an annex link): {path}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"file escapes dataset through a symlink: {path}")


def check_full_dataset(root: Path) -> None:
    if (root / ".git").exists() or (root / ".git").is_symlink():
        raise ValueError("use the plain downloaded dataset, not a Git/annex checkout")
    regular(root / "dataset_description.json", root)
    regular(root / "participants.tsv", root)
    for sub in SUBJECTS:
        for run in range(1, 5):
            stem = root / f"sub-{sub}/func/sub-{sub}_task-trust_run-{run:02d}"
            regular(Path(str(stem) + "_bold.nii.gz"), root)
            regular(Path(str(stem) + "_events.tsv"), root)
            _, rows = read_table(Path(str(stem) + "_events.tsv"))
            if not rows:
                raise ValueError(f"retained run has no events: {stem}")
    count = len(list(root.glob("sub-*/func/*_bold.nii.gz")))
    if count not in EXPECTED_BOLD_COUNTS:
        raise ValueError(f"incomplete/unexpected raw BOLD coverage: {count}; "
                         f"expected one of {sorted(EXPECTED_BOLD_COUNTS)}")


@dataclass
class Change:
    path: str
    before: str
    replacement: bytes | None
    reason: str


def make_plan(root: Path, repository_root: Path | None = None) -> list[Change]:
    root = root.resolve()
    check_full_dataset(root)
    plan: dict[str, Change] = {}

    def add(path: Path, data: bytes | None, reason: str) -> None:
        relative = path.relative_to(root).as_posix()
        exists = path.exists() or path.is_symlink()
        if exists:
            regular(path, root)
        if data is None and not exists:
            return
        if data is not None and exists and path.read_bytes() == data:
            plan.pop(relative, None)
            return
        plan[relative] = Change(relative, digest(path) if exists else "", data, reason)

    def content(path: Path) -> bytes:
        planned = plan.get(path.relative_to(root).as_posix())
        if planned is not None and planned.replacement is not None:
            return planned.replacement
        regular(path, root)
        return path.read_bytes()

    if repository_root is not None:
        # The downloaded tree may predate metadata/ratings that were only added
        # to the sparse upload. Validate the complete candidate release, not
        # the old download. Reuse its guarded 487-file release contract.
        from prepare_openneuro_2_2_release import make_release_plan
        for item in make_release_plan(repository_root.resolve(), root):
            if not item.category.startswith("single_trial"):
                data = item.source.read_bytes()
                if item.expected_sha256 and hashlib.sha256(data).hexdigest() != item.expected_sha256:
                    raise ValueError(f"release source checksum mismatch: {item.source}")
                add(root / item.destination, data, "synchronize approved 2.2.0 small-file release content")

    path = root / "dataset_description.json"
    description = json.loads(content(path))
    if description.get("DatasetType") != "raw":
        description["DatasetType"] = "raw"
        add(path, json_bytes(description), "declare raw dataset explicitly")

    for task in TASKS:
        path = root / f"task-{task}_events.json"
        sidecar = json.loads(content(path))
        presentation = sidecar.get("StimulusPresentation", {})
        if presentation.get("SoftwareRRID") == "SCR_006571":
            presentation["SoftwareRRID"] = "RRID:SCR_006571"
            add(path, json_bytes(sidecar), "correct PsychoPy RRID format")
        path = root / f"task-{task}_bold.json"
        sidecar = json.loads(content(path))
        previous = json.loads(path.read_bytes()) if path.exists() else {}
        inherited = sidecar.get("ImageType", previous.get("ImageType"))
        if inherited is not None:
            images = list(root.glob(f"sub-*/func/*_task-{task}_*_bold.nii.gz"))
            if not images:
                raise ValueError(f"no raw {task} images; this may be a sparse upload tree")
            for image in images:
                child = image.with_name(image.name.removesuffix(".nii.gz") + ".json")
                regular(child, root)
                if json.loads(child.read_text()).get("ImageType") != inherited:
                    raise ValueError(f"cannot remove inherited ImageType: {child}")
            sidecar.pop("ImageType", None)
        add(path, json_bytes(sidecar), "normalize task metadata; per-image ImageType values retained")

    for sub in SUBJECTS:
        func = root / f"sub-{sub}/func"
        events = func / f"sub-{sub}_task-trust_run-05_events.tsv"
        targets = [p for p in func.iterdir() if excluded_name(p.name)]
        if targets:
            regular(events, root)
            fields, rows = read_table(events)
            if rows or not {"onset", "duration", "trial_type"} <= set(fields):
                raise ValueError(f"refusing to exclude non-placeholder events: {events}")
        for path in targets:
            add(path, None, "unsupported Trust run-05 acquisition")

        scans = root / f"sub-{sub}/sub-{sub}_scans.tsv"
        regular(scans, root)
        fields, rows = read_table(scans)
        if "filename" not in fields:
            raise ValueError(f"missing filename column: {scans}")
        retained = [r for r in rows if not excluded_name(r["filename"])]
        if len(retained) != len(rows):
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(retained)
            add(scans, buffer.getvalue().encode(), "remove excluded scan references")
        for path in (root / f"sub-{sub}/fmap").glob("*.json"):
            regular(path, root)
            data = json.loads(path.read_text())
            original = data.get("IntendedFor")
            values = [original] if isinstance(original, str) else original
            if not isinstance(values, list):
                continue
            retained = [v for v in values if not excluded_name(v)]
            if retained != values:
                if retained:
                    data["IntendedFor"] = retained[0] if isinstance(original, str) else retained
                else:
                    del data["IntendedFor"]
                add(path, json_bytes(data), "remove excluded fieldmap targets")

    # Only files naming the exact subject, task and run qualify. No directory
    # removal and no subject-wide anatomical files, transforms or reports.
    derivatives = root / "derivatives"
    if derivatives.exists():
        for directory, dirs, files in os.walk(derivatives, followlinks=False):
            if any((Path(directory) / d).is_symlink() for d in dirs):
                raise ValueError(f"symlinked derivative directory: {directory}")
            for name in files:
                if excluded_name(name):
                    add(Path(directory) / name, None, "derivative of excluded Trust run-05")
    for name in ("README", "CHANGES"):
        path = root / name
        text = content(path).decode()
        if NOTE not in text:
            if name == "README":
                text = text.rstrip() + "\n\n## Trust run exclusions\n\n" + NOTE + "\n"
            else:
                lines = text.splitlines(keepends=True)
                if not lines or not lines[0].startswith("2.2.0"):
                    raise ValueError("CHANGES must start with the draft 2.2.0 entry")
                text = lines[0] + "  - " + NOTE + "\n" + "".join(lines[1:])
            add(path, text.encode(), "document supported release coverage")
    return sorted(plan.values(), key=lambda x: x.path)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".validation-repair-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        if path.exists():
            shutil.copymode(path, temporary)
        else:
            os.chmod(temporary, 0o644)
        os.replace(temporary, path)  # Do not mutate any earlier hard-linked staging copy.
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply_plan(root: Path, backup: Path, plan: list[Change]) -> None:
    root, backup = root.resolve(), backup.resolve()
    if backup.is_relative_to(root) or root.is_relative_to(backup):
        raise ValueError("backup must be outside, and not an ancestor of, the dataset")
    if not plan:
        print("No changes needed")
        return
    backup.mkdir(parents=True, exist_ok=False)
    manifest = []
    # Back up and verify EVERY original before changing the first dataset file.
    for change in plan:
        source = root / change.path
        if change.before:
            regular(source, root)
            if digest(source) != change.before:
                raise ValueError(f"source changed since planning: {source}")
            original = backup / "originals" / change.path
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, original)
            if digest(original) != change.before:
                raise ValueError(f"backup verification failed: {original}")
        elif source.exists() or source.is_symlink():
            raise ValueError(f"new destination appeared since planning: {source}")
        if not source.parent.resolve().is_relative_to(root):
            raise ValueError(f"destination escapes dataset: {source}")
        after = ""
        if change.replacement is not None:
            payload = backup / "replacements" / change.path
            payload.parent.mkdir(parents=True, exist_ok=True)
            payload.write_bytes(change.replacement)
            after = digest(payload)
        action = "exclude" if change.replacement is None else ("replace" if change.before else "create")
        manifest.append(dict(path=change.path, action=action,
                             before=change.before, after=after, reason=change.reason))
    (backup / "repair-manifest.json").write_bytes(json_bytes({"dataset_root": str(root), "files": manifest}))
    with (backup / "deletions.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["path", "sha256", "reason"])
        writer.writerows((c.path, c.before, c.reason) for c in plan if c.replacement is None)
    for change in plan:
        path = root / change.path
        if change.before:
            regular(path, root)
            if digest(path) != change.before:
                raise ValueError(f"source changed before application: {path}")
        elif path.exists() or path.is_symlink():
            raise ValueError(f"new destination appeared before application: {path}")
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError(f"destination escapes dataset: {path}")
        if change.replacement is None:
            path.unlink()  # Verified original is retained in the external backup.
        else:
            atomic_write(path, change.replacement)
    (backup / "COMPLETE").write_text("All planned repairs applied. No remote changes made.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.dataset_root.resolve()
    try:
        plan = make_plan(root, args.repository_root)
        for change in plan:
            print(f"{'EXCLUDE' if change.replacement is None else 'REPLACE'}: {change.path}")
        print(f"Plan: {sum(c.replacement is None for c in plan)} exclusions; "
              f"{sum(c.replacement is not None for c in plan)} replacements")
        if args.apply:
            if args.backup_root is None:
                raise ValueError("--apply requires --backup-root")
            apply_plan(root, args.backup_root.resolve(), plan)
            print("PASS: local repairs applied; originals backed up. OpenNeuro is unchanged.")
        else:
            print("Preview only: nothing changed")
        print("Do not upload yet: validate the complete dataset and review deletions.tsv first.")
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f"ERROR: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
