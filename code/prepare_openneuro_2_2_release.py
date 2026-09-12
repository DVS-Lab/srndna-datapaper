#!/usr/bin/env python3
"""Build a guarded sparse staging tree for the ds003745 2.2.0 upload.

The OpenNeuro uploader preserves remote files that are absent from the local
source unless ``--delete`` is requested.  This script therefore stages only
the files intended for the focused 2.2.0 update and refuses any unexpected
counts.  It never changes the downloaded dataset.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]

ROOT_METADATA = (
    ".bidsignore",
    "CHANGES",
    "README",
    "dataset_description.json",
    "participants.json",
    "participants.tsv",
)

BEHAVIOR_SIDECARS = (
    "task-sharedreward_beh.json",
    "task-trust_beh.json",
    "task-ultimatum_beh.json",
)

EVENT_REPAIRS = (
    "sub-144/func/sub-144_task-sharedreward_run-01_events.tsv",
    "sub-144/func/sub-144_task-sharedreward_run-02_events.tsv",
    "sub-144/func/sub-144_task-ultimatum_run-01_events.tsv",
    "sub-144/func/sub-144_task-ultimatum_run-02_events.tsv",
)

SUB144_SINGLE_TRIALS = (
    "derivatives/single_trials/sub-144/"
    "sub-144_task-sharedreward_run-01_singletrial-Act.nii.gz",
    "derivatives/single_trials/sub-144/"
    "sub-144_task-sharedreward_run-02_singletrial-Act.nii.gz",
    "derivatives/single_trials/sub-144/"
    "sub-144_task-ultimatum_run-01_singletrial-Act.nii.gz",
    "derivatives/single_trials/sub-144/"
    "sub-144_task-ultimatum_run-02_singletrial-Act.nii.gz",
)

REPRODUCIBILITY_FILES = (
    "code/L1LSSstats.sh",
    "code/README.md",
    "code/apply_openneuro_event_repairs.py",
    "code/audit_task_ratings.py",
    "code/export_task_ratings_to_bids.py",
    "code/lss_input_fingerprint.sh",
    "code/makeSingleTrials.py",
    "code/makeSingleTrials_trust.py",
    "code/make_fsl_confounds.py",
    "code/pack_L1LSSstats.sh",
    "code/recover_sub144_sharedreward_events.py",
    "code/recover_sub144_ultimatum_events.py",
    "code/run_L1LSSstats.sh",
    "code/behavioral_analyses/sub-144_task-ultimatum_run-01_events.tsv",
    "code/behavioral_analyses/sub-144_task-ultimatum_run-02_events.tsv",
    "stimuli/convertUG_BIDS.m",
    "stimuli/psychopy/SRratings.csv",
    "stimuli/psychopy/SR_postRatings.py",
    "stimuli/psychopy/Trust.csv",
    "stimuli/psychopy/TrustRatings.py",
    "stimuli/psychopy/UGRatings_Post.csv",
    "stimuli/psychopy/UGRatings_Pre.csv",
    "stimuli/psychopy/UG_pre_post_Ratings.py",
    "templates/L1LSS_task-sharedreward_model-01_type-act.fsf",
    "templates/L1LSS_task-trust_model-01_type-act.fsf",
    "templates/L1LSS_task-ultimatum_model-01_type-act.fsf",
)


@dataclass(frozen=True)
class ReleaseFile:
    category: str
    source: Path
    destination: Path
    expected_sha256: str = ""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Output inventory (default: next to the staging directory).",
    )
    parser.add_argument(
        "--copy-large-files",
        action="store_true",
        help="Copy NIfTI files instead of hard-linking when possible.",
    )
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def add_repo_files(
    plan: list[ReleaseFile], repo_root: Path, paths: Iterable[str], category: str
) -> None:
    for relative in paths:
        plan.append(
            ReleaseFile(category, repo_root / "bids" / relative, Path(relative))
        )


def make_release_plan(
    repo_root: Path,
    dataset_root: Path,
    *,
    expected_ratings: int = 220,
    expected_trust_images: int = 218,
) -> list[ReleaseFile]:
    plan: list[ReleaseFile] = []
    add_repo_files(plan, repo_root, ROOT_METADATA, "root_metadata")
    add_repo_files(plan, repo_root, BEHAVIOR_SIDECARS, "behavior_sidecar")
    add_repo_files(plan, repo_root, EVENT_REPAIRS, "event_repair")

    rating_manifest = (
        repo_root / "results/ratings_audit/ratings_bids_export_manifest.tsv"
    )
    rating_rows = read_tsv(rating_manifest)
    if len(rating_rows) != expected_ratings:
        raise ValueError(
            f"expected {expected_ratings} rating files, found {len(rating_rows)}"
        )
    if any(row.get("participant_id") == "sub-143" for row in rating_rows):
        raise ValueError("ratings manifest unexpectedly contains sub-143")
    for row in rating_rows:
        relative = Path(row["destination"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe rating destination: {relative}")
        plan.append(
            ReleaseFile(
                "behavior_tsv",
                repo_root / "bids" / relative,
                relative,
                row["sha256"],
            )
        )

    trust_images = sorted(
        dataset_root.glob(
            "derivatives/single_trials/sub-*/"
            "sub-*_task-trust_run-*_singletrial-Act.nii.gz"
        )
    )
    if len(trust_images) != expected_trust_images:
        raise ValueError(
            f"expected {expected_trust_images} Trust single-trial images, "
            f"found {len(trust_images)}"
        )
    for source in trust_images:
        plan.append(
            ReleaseFile(
                "single_trial_trust",
                source,
                source.relative_to(dataset_root),
            )
        )

    for relative_text in SUB144_SINGLE_TRIALS:
        relative = Path(relative_text)
        plan.append(
            ReleaseFile(
                "single_trial_sub144", dataset_root / relative, relative
            )
        )

    for relative_text in REPRODUCIBILITY_FILES:
        relative = Path(relative_text)
        plan.append(
            ReleaseFile("reproducibility", repo_root / relative, relative)
        )

    destinations = [item.destination.as_posix() for item in plan]
    if len(destinations) != len(set(destinations)):
        duplicates = sorted(
            path for path in set(destinations) if destinations.count(path) > 1
        )
        raise ValueError(f"duplicate release destinations: {duplicates}")
    unexpected_events = sorted(
        path
        for path in destinations
        if path.startswith("sub-")
        and path.endswith("_events.tsv")
        and path not in EVENT_REPAIRS
    )
    if unexpected_events:
        raise ValueError(f"unexpected event files in release: {unexpected_events}")
    missing = [str(item.source) for item in plan if not item.source.is_file()]
    if missing:
        raise FileNotFoundError("missing release inputs:\n" + "\n".join(missing))
    empty = [str(item.source) for item in plan if item.source.stat().st_size == 0]
    if empty:
        raise ValueError("empty release inputs:\n" + "\n".join(empty))
    if len(plan) > 500:
        raise ValueError(f"release plan has {len(plan)} files; hard limit is 500")
    return plan


def materialize(
    plan: list[ReleaseFile], staging_root: Path, *, copy_large_files: bool
) -> list[dict[str, object]]:
    if staging_root.exists():
        raise FileExistsError(
            f"staging root already exists; move it aside first: {staging_root}"
        )
    staging_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{staging_root.name}-building-", dir=staging_root.parent)
    )
    inventory: list[dict[str, object]] = []
    try:
        for index, item in enumerate(plan, 1):
            destination = temporary / item.destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            method = "copy"
            if item.category.startswith("single_trial") and not copy_large_files:
                try:
                    os.link(item.source, destination)
                    method = "hardlink"
                except OSError:
                    shutil.copy2(item.source, destination)
            else:
                shutil.copy2(item.source, destination)
            digest = sha256(destination)
            if item.expected_sha256 and digest != item.expected_sha256:
                raise ValueError(
                    f"checksum mismatch for {item.destination}: "
                    f"expected {item.expected_sha256}, found {digest}"
                )
            inventory.append(
                {
                    "category": item.category,
                    "source": str(item.source),
                    "destination": item.destination.as_posix(),
                    "bytes": destination.stat().st_size,
                    "sha256": digest,
                    "materialization": method,
                }
            )
            if index % 25 == 0 or index == len(plan):
                print(f"Staged {index}/{len(plan)} files")
        os.replace(temporary, staging_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return inventory


def write_manifest(path: Path, inventory: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "category",
                "source",
                "destination",
                "bytes",
                "sha256",
                "materialization",
            ),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(inventory)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repository_root.resolve()
    dataset_root = args.dataset_root.resolve()
    staging_root = args.staging_root.resolve()
    if not (dataset_root / "dataset_description.json").is_file():
        raise SystemExit(f"ERROR: not a BIDS dataset root: {dataset_root}")
    manifest = (
        args.manifest.resolve()
        if args.manifest
        else staging_root.parent / f"{staging_root.name}-manifest.tsv"
    )
    if is_within(staging_root, dataset_root) or is_within(staging_root, repo_root):
        raise SystemExit(
            "ERROR: staging root must be outside both the downloaded dataset "
            "and the code repository"
        )
    if is_within(manifest, staging_root):
        raise SystemExit("ERROR: release manifest must be outside the staging tree")
    try:
        plan = make_release_plan(repo_root, dataset_root)
        inventory = materialize(
            plan, staging_root, copy_large_files=args.copy_large_files
        )
        write_manifest(manifest, inventory)
    except (OSError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}") from error

    counts: dict[str, int] = {}
    for row in inventory:
        category = str(row["category"])
        counts[category] = counts.get(category, 0) + 1
    print(f"PASS: built guarded OpenNeuro 2.2.0 staging tree with {len(inventory)} files")
    for category in sorted(counts):
        print(f"  {category}: {counts[category]}")
    print("PASS: event files are restricted to the four sub-144 repairs")
    print(f"Staging root: {staging_root}")
    print(f"Manifest: {manifest}")
    print("Upload without --delete so all other remote dataset files are preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
