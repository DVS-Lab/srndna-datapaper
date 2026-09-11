#!/usr/bin/env python3
"""Safely apply verified sub-144 event repairs to an OpenNeuro dataset tree."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class Repair:
    source: str
    destination: str
    published_sha256: str
    required: bool = True
    accepted_previous_sha256: tuple[str, ...] = ()


REPAIRS = (
    Repair(
        "bids/sub-144/func/sub-144_task-ultimatum_run-01_events.tsv",
        "sub-144/func/sub-144_task-ultimatum_run-01_events.tsv",
        "5491a2d2db11787d57c40ed6ec1d63ed1256e6c0276400f519e57bc5459608b7",
    ),
    Repair(
        "bids/sub-144/func/sub-144_task-ultimatum_run-02_events.tsv",
        "sub-144/func/sub-144_task-ultimatum_run-02_events.tsv",
        "467069b092d73c11ce1a0740b3ac43f8a4f791cff5d71ceb0cd0cb44e6468c01",
    ),
    Repair(
        "bids/sub-144/func/sub-144_task-ultimatum_run-01_events.tsv",
        "derivatives/behavioraldata/sub-144_task-ultimatum_run-01_events.tsv",
        "5491a2d2db11787d57c40ed6ec1d63ed1256e6c0276400f519e57bc5459608b7",
        required=False,
    ),
    Repair(
        "bids/sub-144/func/sub-144_task-ultimatum_run-02_events.tsv",
        "derivatives/behavioraldata/sub-144_task-ultimatum_run-02_events.tsv",
        "467069b092d73c11ce1a0740b3ac43f8a4f791cff5d71ceb0cd0cb44e6468c01",
        required=False,
    ),
    Repair(
        "bids/sub-144/func/sub-144_task-ultimatum_run-01_events.tsv",
        "code/behavioral_analyses/sub-144_task-ultimatum_run-01_events.tsv",
        "5491a2d2db11787d57c40ed6ec1d63ed1256e6c0276400f519e57bc5459608b7",
        required=False,
    ),
    Repair(
        "bids/sub-144/func/sub-144_task-ultimatum_run-02_events.tsv",
        "code/behavioral_analyses/sub-144_task-ultimatum_run-02_events.tsv",
        "467069b092d73c11ce1a0740b3ac43f8a4f791cff5d71ceb0cd0cb44e6468c01",
        required=False,
    ),
    Repair(
        "bids/sub-144/func/sub-144_task-sharedreward_run-01_events.tsv",
        "sub-144/func/sub-144_task-sharedreward_run-01_events.tsv",
        "5a7762761b4193e30e0b1b557850ee46279b249bd0103b6487549c52b9e9da6f",
    ),
    Repair(
        "bids/sub-144/func/sub-144_task-sharedreward_run-02_events.tsv",
        "sub-144/func/sub-144_task-sharedreward_run-02_events.tsv",
        "e778954c147f0c2e62f34f06678fb9f8ac9665cb6d0bddb536ca2f0fb0a2bd0f",
    ),
    Repair(
        "bids/CHANGES",
        "CHANGES",
        "ff86e33b0f82a4d4e5ed7c48d60ffb41b13e9c8e109f025f8d1684dce292b3e5",
        accepted_previous_sha256=(
            "e5ce7ce76906a244b1fbab2b0bcb25d6e749ed2d80a1dd80c8e1184b671d9140",
        ),
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.repair-tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--backup-root",
        type=Path,
        help="directory outside the dataset for originals and the repair manifest",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write repairs; without this flag the command is a read-only preview",
    )
    return parser


def run(repo_root: Path, dataset_root: Path, backup_root: Path | None, apply: bool) -> int:
    dataset_root = dataset_root.resolve()
    if not (dataset_root / "dataset_description.json").is_file():
        raise ValueError(f"not an OpenNeuro dataset root: {dataset_root}")
    if apply and backup_root is None:
        raise ValueError("--backup-root is required with --apply")
    if backup_root is not None:
        backup_root = backup_root.resolve()
        if backup_root == dataset_root or dataset_root in backup_root.parents:
            raise ValueError("backup root must be outside the OpenNeuro dataset")

    rows: list[dict[str, str]] = []
    failures = 0
    for repair in REPAIRS:
        source = repo_root / repair.source
        destination = dataset_root / repair.destination
        if not source.is_file():
            print(f"ERROR source missing: {source}", file=sys.stderr)
            failures += 1
            continue
        corrected_hash = sha256(source)
        if not destination.exists():
            if repair.required:
                print(f"ERROR required destination missing: {destination}", file=sys.stderr)
                failures += 1
            else:
                print(f"SKIP optional destination absent: {repair.destination}")
            continue

        before_hash = sha256(destination)
        if before_hash == corrected_hash:
            action = "already-current"
        elif before_hash in {
            repair.published_sha256,
            *repair.accepted_previous_sha256,
        }:
            action = "replace"
        else:
            accepted_hashes = "\n".join(
                f"  accepted prior: {candidate}"
                for candidate in (
                    repair.published_sha256,
                    *repair.accepted_previous_sha256,
                )
            )
            print(
                f"ERROR unexpected destination hash: {repair.destination}\n"
                f"  observed:  {before_hash}\n"
                f"{accepted_hashes}\n"
                f"  corrected: {corrected_hash}",
                file=sys.stderr,
            )
            failures += 1
            continue

        print(
            f"{action.upper()}: {repair.destination}\n"
            f"  {before_hash} -> {corrected_hash}"
        )
        rows.append(
            {
                "path": repair.destination,
                "before_sha256": before_hash,
                "after_sha256": corrected_hash,
                "action": action,
            }
        )

    if failures:
        print(f"Preflight failed with {failures} error(s); nothing was changed", file=sys.stderr)
        return 1
    if not apply:
        replacements = sum(row["action"] == "replace" for row in rows)
        print(f"Preview complete: {replacements} file(s) would be replaced; nothing was changed")
        return 0

    assert backup_root is not None
    for row in rows:
        if row["action"] != "replace":
            continue
        source = repo_root / next(
            repair.source for repair in REPAIRS if repair.destination == row["path"]
        )
        destination = dataset_root / row["path"]
        backup = backup_root / "originals" / row["path"]
        if backup.exists():
            if sha256(backup) != row["before_sha256"]:
                raise ValueError(f"existing backup does not match destination: {backup}")
        else:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
        atomic_copy(source, destination)
        if sha256(destination) != row["after_sha256"]:
            raise RuntimeError(f"post-write verification failed: {destination}")

    backup_root.mkdir(parents=True, exist_ok=True)
    manifest = backup_root / "event-repair-manifest.tsv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("path", "before_sha256", "after_sha256", "action"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Applied repairs and wrote manifest: {manifest}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        return run(repo_root, args.dataset_root, args.backup_root, args.apply)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
