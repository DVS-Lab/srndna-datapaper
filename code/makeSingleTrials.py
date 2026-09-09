#!/usr/bin/env python3
"""Create least-squares-separate (LSS) EV files from BIDS events files."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable, Mapping, Sequence


TASKS = ("ultimatum", "sharedreward", "trust")


class NoEstimableEvents(ValueError):
    """Raised for a valid events table that has no events modeled by LSS."""


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


def event_pattern(task: str) -> re.Pattern[str]:
    return re.compile(
        rf"sub-(?P<sub>\d+)_task-{re.escape(task)}_run-(?P<run>\d+)_events\.tsv$"
    )


def read_events(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)
    required = {"onset", "duration", "trial_type"}
    missing = required.difference(reader.fieldnames or [])
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(sorted(missing))}")
    return rows


def deduplicate_last(
    events: Iterable[Mapping[str, str]],
) -> list[Mapping[str, str]]:
    """Deduplicate onset/duration pairs while retaining the final matching row."""
    seen: set[tuple[str, str]] = set()
    kept_reversed: list[Mapping[str, str]] = []
    for row in reversed(list(events)):
        key = (row["onset"], row["duration"])
        if key not in seen:
            seen.add(key)
            kept_reversed.append(row)
    return list(reversed(kept_reversed))


def estimation_events(
    task: str, events: Iterable[Mapping[str, str]]
) -> list[Mapping[str, str]]:
    if task == "trust":
        selected = [row for row in events if "outcome" in row["trial_type"]]
    else:
        selected = [
            row
            for row in events
            if "event_RT" not in row["trial_type"]
            and "block_" not in row["trial_type"]
        ]
    return deduplicate_last(selected)


def write_three_column(rows: Iterable[Mapping[str, str]], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        for row in rows:
            writer.writerow([row["onset"], row["duration"], "1"])
    temporary.replace(path)


def remove_stale_generated_files(output_dir: Path, expected: set[Path]) -> None:
    patterns = (
        "trialmodel-*_estimage-single.tsv",
        "trialmodel-*_estimage-other.tsv",
        "trialmodel-decisionphase_.tsv",
    )
    for pattern in patterns:
        for candidate in output_dir.glob(pattern):
            if candidate not in expected:
                candidate.unlink()


def make_run_evs(
    task: str,
    event_file: Path,
    output_root: Path,
    *,
    clean: bool = False,
    dry_run: bool = False,
) -> int:
    if task not in TASKS:
        raise ValueError(f"unsupported task: {task}")
    match = event_pattern(task).match(event_file.name)
    if not match:
        raise ValueError(f"not a {task} events file: {event_file}")

    subject = match.group("sub")
    run = int(match.group("run"))
    output_dir = (
        output_root
        / f"sub-{subject}"
        / "SingleTrialEVs"
        / f"task-{task}"
        / f"run{run:02d}"
    )
    events = read_events(event_file)
    trials = estimation_events(task, events)
    if not trials:
        if clean and not dry_run and output_dir.is_dir():
            remove_stale_generated_files(output_dir, set())
        raise NoEstimableEvents(f"no estimable {task} trials found in {event_file}")
    if dry_run:
        return len(trials)

    output_dir.mkdir(parents=True, exist_ok=True)

    expected: set[Path] = set()
    if task == "trust":
        decision_file = output_dir / "trialmodel-decisionphase_.tsv"
        decisions = [row for row in events if "choice" in row["trial_type"]]
        if not decisions:
            raise ValueError(f"no Trust decision events found in {event_file}")
        write_three_column(decisions, decision_file)
        expected.add(decision_file)

    for trial_index, trial in enumerate(trials, start=1):
        single_file = output_dir / f"trialmodel-{trial_index}_estimage-single.tsv"
        other_file = output_dir / f"trialmodel-{trial_index}_estimage-other.tsv"
        write_three_column([trial], single_file)
        write_three_column(
            trials[: trial_index - 1] + trials[trial_index:], other_file
        )
        expected.update((single_file, other_file))

    if clean:
        remove_stale_generated_files(output_dir, expected)
    return len(trials)


def build_parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=TASKS)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        help=(
            "OpenNeuro-style BIDS root containing sub-* and derivatives/; "
            "cannot be combined with --bids-dir or --output-root"
        ),
    )
    parser.add_argument(
        "--bids-dir",
        type=Path,
        help="events root (default: the GitHub repository's bids directory)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="FSL EV output root (default: repository derivatives/fsl/EVfiles)",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--all-subjects",
        action="store_true",
        help="generate EVs for every subject with events for this task",
    )
    scope.add_argument(
        "--subject",
        action="append",
        type=normalize_subject,
        help="limit generation to a subject (repeatable; accepts 144 or sub-144)",
    )
    parser.add_argument(
        "--run",
        action="append",
        type=normalize_run,
        help="limit generation to a run (repeatable; accepts 2 or run-02)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove stale generated EV files after successfully writing selected runs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate inputs and report trial counts without writing files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    if args.dataset_root and (args.bids_dir or args.output_root):
        parser.error("--dataset-root cannot be combined with --bids-dir or --output-root")
    if args.dataset_root:
        bids_dir = args.dataset_root
        output_root = args.dataset_root / "derivatives" / "fsl" / "EVfiles"
    else:
        bids_dir = args.bids_dir or repo_root / "bids"
        output_root = (
            args.output_root or repo_root / "derivatives" / "fsl" / "EVfiles"
        )
    selected_subjects = set(args.subject or [])
    selected_runs = set(args.run or [])
    pattern = event_pattern(args.task)
    event_files = sorted(
        bids_dir.glob(f"sub-*/func/sub-*_task-{args.task}_run-*_events.tsv")
    )

    generated_runs = 0
    generated_trials = 0
    skipped_runs = 0
    for event_file in event_files:
        match = pattern.match(event_file.name)
        if not match:
            continue
        if selected_subjects and match.group("sub") not in selected_subjects:
            continue
        if selected_runs and int(match.group("run")) not in selected_runs:
            continue
        try:
            trials = make_run_evs(
                args.task,
                event_file,
                output_root,
                clean=args.clean,
                dry_run=args.dry_run,
            )
        except NoEstimableEvents as error:
            if not args.all_subjects:
                parser.error(str(error))
            skipped_runs += 1
            print(f"Skipped {event_file}: no estimable trials")
            continue
        generated_runs += 1
        generated_trials += trials
        print(
            f"sub-{match.group('sub')} run-{int(match.group('run')):02d}: "
            f"{trials} trials"
        )

    if not generated_runs:
        parser.error("no events files matched the requested task/subject/run scope")
    action = "Validated" if args.dry_run else "Generated"
    print(
        f"{action} {args.task} LSS EVs for {generated_trials} trials "
        f"across {generated_runs} runs"
    )
    if skipped_runs:
        print(f"Skipped {skipped_runs} valid events files with no estimable trials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
