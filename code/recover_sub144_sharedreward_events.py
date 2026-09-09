#!/usr/bin/env python3
"""Rebuild sub-144 Shared Reward events from its second logged session.

Each sub-144 raw CSV contains two complete acquisition sessions separated by a
repeated header.  The first session reproduces the published sub-143 events;
the second session is sub-144.  The original MATLAB converter stopped at the
repeated non-numeric header, so both subjects were published with session 1.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence


EXPECTED_HEADER = [
    "TrialNumber",
    "Trialn",
    "Feedback",
    "ITI",
    "Partner",
    "BlockType",
    "Blockn",
    "ran",
    "order",
    "decision_onset",
    "resp",
    "resp_onset",
    "rt",
    "outcome_val",
    "outcome_onset",
    "outcome_offset",
    "trialDuration",
    "ITIonset",
    "ITIoffset",
]
OUTPUT_HEADER = ["onset", "duration", "trial_type", "response_time"]
BLOCK_STARTS = {1, 9, 17, 25, 33, 41, 49, 57, 65}
PARTNERS = {1: "computer", 2: "stranger", 3: "friend"}
FEEDBACK = {1: "punish", 2: "neutral", 3: "reward"}
BLOCK_TYPES = {
    1: "computer_punish",
    2: "computer_reward",
    3: "stranger_punish",
    4: "stranger_reward",
    5: "friend_punish",
    6: "friend_reward",
}


def _as_int(value: str, field: str) -> int:
    number = float(value)
    if not number.is_integer():
        raise ValueError(f"{field} must be an integer, got {value!r}")
    return int(number)


def read_logged_sessions(path: Path) -> list[list[dict[str, str]]]:
    """Read and validate the two 72-trial sessions in a concatenated raw log."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))

    header_indices = [index for index, row in enumerate(rows) if row == EXPECTED_HEADER]
    if header_indices != [0, 73]:
        raise ValueError(
            f"{path}: expected headers at rows 1 and 74; found "
            f"{[index + 1 for index in header_indices]}"
        )

    sessions: list[list[dict[str, str]]] = []
    for session_number, (start, stop) in enumerate(((1, 73), (74, len(rows))), start=1):
        session_rows = rows[start:stop]
        if len(session_rows) != 72:
            raise ValueError(
                f"{path}: session {session_number} has {len(session_rows)} trials, expected 72"
            )
        if any(len(row) != len(EXPECTED_HEADER) for row in session_rows):
            raise ValueError(f"{path}: session {session_number} has a malformed row")
        records = [dict(zip(EXPECTED_HEADER, row)) for row in session_rows]
        trial_numbers = [_as_int(row["TrialNumber"], "TrialNumber") for row in records]
        if trial_numbers != list(range(1, 73)):
            raise ValueError(
                f"{path}: session {session_number} trial numbers are not exactly 1 through 72"
            )
        sessions.append(records)
    return sessions


def _format_float(value: str | float) -> str:
    return f"{float(value):.6f}"


def make_event_rows(records: Sequence[Mapping[str, str]]) -> list[list[str]]:
    """Convert one validated raw session using the original MATLAB rules."""
    output: list[list[str]] = []
    for trial, record in enumerate(records, start=1):
        if _as_int(record["TrialNumber"], "TrialNumber") != trial:
            raise ValueError(f"unexpected trial order at trial {trial}")

        partner = _as_int(record["Partner"], "Partner")
        feedback = _as_int(record["Feedback"], "Feedback")
        block_type = _as_int(record["BlockType"], "BlockType")
        if partner not in PARTNERS:
            raise ValueError(f"trial {trial}: invalid Partner value {partner}")
        if feedback not in FEEDBACK:
            raise ValueError(f"trial {trial}: invalid Feedback value {feedback}")
        if block_type not in BLOCK_TYPES:
            raise ValueError(f"trial {trial}: invalid BlockType value {block_type}")

        onset = _format_float(record["decision_onset"])
        duration = _format_float(record["trialDuration"])
        rt = float(record["rt"])
        if rt == 999:
            output.append([onset, duration, "missed_trial", "n/a"])
        else:
            event = f"event_{PARTNERS[partner]}_{FEEDBACK[feedback]}"
            output.append([onset, duration, event, _format_float(rt)])

        if trial in BLOCK_STARTS:
            output.append(
                [onset, "33.500000", f"block_{BLOCK_TYPES[block_type]}", "n/a"]
            )
    return output


def render_tsv(rows: Iterable[Sequence[str]]) -> str:
    lines = ["\t".join(OUTPUT_HEADER)]
    lines.extend("\t".join(row) for row in rows)
    return "\n".join(lines) + "\n"


def target_path(repo_root: Path, run: int) -> Path:
    return (
        repo_root
        / "bids"
        / "sub-144"
        / "func"
        / f"sub-144_task-sharedreward_run-{run:02d}_events.tsv"
    )


def rebuild(repo_root: Path, check: bool = False) -> int:
    changed: list[Path] = []
    for raw_run in (0, 1):
        raw_path = (
            repo_root
            / "stimuli"
            / "psychopy"
            / "logs"
            / "144"
            / f"sub-144_task-sharedreward_run-{raw_run}_raw.csv"
        )
        sessions = read_logged_sessions(raw_path)
        rendered = render_tsv(make_event_rows(sessions[1]))
        target = target_path(repo_root, raw_run + 1)
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current != rendered:
            changed.append(target)
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(rendered, encoding="utf-8")

    if check and changed:
        for path in changed:
            print(f"OUTDATED: {path.relative_to(repo_root)}", file=sys.stderr)
        return 1
    if check:
        print("PASS: tracked sub-144 Shared Reward events match raw session 2")
    else:
        print(f"Updated {len(changed)} tracked event files")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate tracked outputs without changing them",
    )
    args = parser.parse_args()
    return rebuild(args.repo_root.resolve(), check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
