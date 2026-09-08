#!/usr/bin/env python3
"""Create least-squares-separate (LSS) EV files for the Trust task."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable, Mapping


EVENT_PATTERN = re.compile(r"sub-(?P<sub>\d+)_task-trust_run-(?P<run>\d+)_events\.tsv$")


def write_three_column(rows: Iterable[Mapping[str, str]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        for row in rows:
            writer.writerow([row["onset"], row["duration"], "1"])


def read_events(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    required = {"onset", "duration", "trial_type"}
    if not rows:
        raise ValueError(f"no events found in {path}")
    missing = required.difference(rows[0])
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
    return rows


def deduplicate_outcomes(events: Iterable[Mapping[str, str]]) -> list[Mapping[str, str]]:
    """Return outcome rows deduplicated by onset/duration, retaining the last."""
    seen: set[tuple[str, str]] = set()
    kept_reversed: list[Mapping[str, str]] = []
    for row in reversed(list(events)):
        if "outcome" not in row["trial_type"]:
            continue
        key = (row["onset"], row["duration"])
        if key not in seen:
            seen.add(key)
            kept_reversed.append(row)
    return list(reversed(kept_reversed))


def make_run_evs(event_file: Path, output_root: Path, clean: bool = False) -> int:
    match = EVENT_PATTERN.match(event_file.name)
    if not match:
        raise ValueError(f"not a Trust events file: {event_file}")

    subject = match.group("sub")
    run = match.group("run")
    output_dir = (
        output_root / f"sub-{subject}" / "SingleTrialEVs" / "task-trust" / f"run{run}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    if clean:
        for pattern in (
            "trialmodel-*_estimage-single.tsv",
            "trialmodel-*_estimage-other.tsv",
        ):
            for stale_file in output_dir.glob(pattern):
                stale_file.unlink()

    events = read_events(event_file)
    decisions = [row for row in events if "choice" in row["trial_type"]]
    write_three_column(decisions, output_dir / "trialmodel-decisionphase_.tsv")

    outcomes = deduplicate_outcomes(events)
    for trial_index, _ in enumerate(outcomes, start=1):
        write_three_column(
            [outcomes[trial_index - 1]],
            output_dir / f"trialmodel-{trial_index}_estimage-single.tsv",
        )
        write_three_column(
            outcomes[: trial_index - 1] + outcomes[trial_index:],
            output_dir / f"trialmodel-{trial_index}_estimage-other.tsv",
        )
    return len(outcomes)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bids-dir",
        type=Path,
        default=repo_root / "bids",
        help="BIDS dataset root (default: repository bids directory)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=repo_root / "derivatives" / "fsl" / "EVfiles",
        help="FSL EV output root",
    )
    parser.add_argument(
        "--subject",
        action="append",
        help="limit generation to a subject label, without 'sub-' (repeatable)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove old generated single/other EV files in each selected run first",
    )
    args = parser.parse_args()

    selected_subjects = set(args.subject or [])
    event_files = sorted(args.bids_dir.glob("sub-*/func/sub-*_task-trust_run-*_events.tsv"))
    generated_runs = 0
    generated_trials = 0
    for event_file in event_files:
        match = EVENT_PATTERN.match(event_file.name)
        if not match:
            continue
        if selected_subjects and match.group("sub") not in selected_subjects:
            continue
        trials = make_run_evs(event_file, args.output_root, clean=args.clean)
        generated_runs += 1
        generated_trials += trials

    if not generated_runs:
        parser.error("no matching Trust events files were found")
    print(f"Generated Trust LSS EVs for {generated_trials} trials across {generated_runs} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
