#!/usr/bin/env python3
"""Create numeric FSL confound matrices from fMRIPrep confounds TSV files."""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import sys
from pathlib import Path
from typing import Sequence


TASKS = ("ultimatum", "sharedreward", "trust")
MOTION = ("trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z")
ACOMPCOR = tuple(f"a_comp_cor_{index:02d}" for index in range(6))
FRAMEWISE_DISPLACEMENT = ("framewise_displacement",)
SOURCE_PATTERN = re.compile(
    r"sub-(?P<subject>\d+)_task-(?P<task>[A-Za-z0-9]+)_run-(?P<run>\d+)_"
    r"desc-confounds_(?:timeseries|regressors)\.tsv$"
)


def normalize_subject(value: str) -> str:
    value = value.removeprefix("sub-")
    if not value.isdigit():
        raise argparse.ArgumentTypeError("subject must be numeric, optionally prefixed by sub-")
    return value


def normalize_run(value: str) -> int:
    value = value.removeprefix("run-")
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("run must be a positive integer")
    return int(value)


def selected_columns(fieldnames: Sequence[str]) -> list[str]:
    cosine = [name for name in fieldnames if name.startswith("cosine")]
    nonsteady = [name for name in fieldnames if name.startswith("non_steady_state")]
    required = [*MOTION, *ACOMPCOR, *FRAMEWISE_DISPLACEMENT]
    missing = [name for name in required if name not in fieldnames]
    if missing:
        raise ValueError(f"missing required confound columns: {', '.join(missing)}")
    return [*cosine, *nonsteady, *MOTION, *ACOMPCOR, *FRAMEWISE_DISPLACEMENT]


def numeric_value(value: str | None, *, column: str, row: int) -> str:
    if value is None or value.strip().lower() in {"", "n/a", "na", "nan"}:
        return "0"
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"row {row}, {column}: non-numeric value {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"row {row}, {column}: non-finite value {value!r}")
    return value


def convert(source: Path, destination: Path, *, dry_run: bool = False) -> int:
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        columns = selected_columns(reader.fieldnames or [])
        output_rows = [
            [numeric_value(record.get(column), column=column, row=row_number)
             for column in columns]
            for row_number, record in enumerate(reader, start=2)
        ]
    if not output_rows:
        raise ValueError(f"empty confounds table: {source}")
    if dry_run:
        return len(output_rows)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerows(output_rows)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return len(output_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all-subjects", action="store_true")
    scope.add_argument("--subject", action="append", type=normalize_subject)
    parser.add_argument("--run", action="append", type=normalize_run)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fmriprep_root = args.dataset_root / "derivatives" / "fmriprep"
    if not fmriprep_root.is_dir():
        raise SystemExit(f"fMRIPrep directory not found: {fmriprep_root}")
    selected_subjects = set(args.subject or [])
    selected_runs = set(args.run or [])

    converted = 0
    total_rows = 0
    failures: list[str] = []
    for source in sorted(fmriprep_root.glob("sub-*/func/*_desc-confounds_*.tsv")):
        match = SOURCE_PATTERN.match(source.name)
        if not match or match.group("task") != args.task:
            continue
        subject = match.group("subject")
        run_label = match.group("run")
        run = int(run_label)
        if selected_subjects and subject not in selected_subjects:
            continue
        if selected_runs and run not in selected_runs:
            continue

        bold = source.with_name(
            f"sub-{subject}_task-{args.task}_run-{run_label}_"
            "space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
        )
        if not bold.is_file():
            failures.append(f"missing preprocessed BOLD for {source}")
            continue
        destination = (
            args.output_root
            / f"sub-{subject}"
            / f"sub-{subject}_task-{args.task}_run-{run}_desc-fslConfounds.tsv"
        )
        try:
            rows = convert(source, destination, dry_run=args.dry_run)
        except ValueError as error:
            failures.append(f"{source}: {error}")
            continue
        converted += 1
        total_rows += rows
        print(f"sub-{subject} run-{run}: {rows} rows")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise SystemExit(f"confound preflight failed with {len(failures)} error(s)")
    if converted == 0:
        raise SystemExit("no matching fMRIPrep confounds files")
    action = "Validated" if args.dry_run else "Generated"
    print(
        f"{action} {converted} {args.task} FSL confound matrices "
        f"containing {total_rows} rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
