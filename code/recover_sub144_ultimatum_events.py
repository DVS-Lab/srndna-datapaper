#!/usr/bin/env python3
"""Rebuild sub-144 Ultimatum events from its second logged session.

Each sub-144 raw CSV contains two complete acquisition sessions separated by a
repeated header.  The first session is the recovered sub-143 session; the
second session is sub-144.  This script validates that structure and writes the
sub-144 BIDS events files plus the two tracked mirrors used by legacy analyses.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence


EXPECTED_HEADER = [
    "TrialNumber",
    "IsFairBlock",
    "Trialn",
    "Offer",
    "Partner",
    "ITI",
    "Blockn",
    "ran",
    "order",
    "decision_onset",
    "resp",
    "rt",
    "resp_onset",
    "decision_offset",
    "trialDuration",
    "ITIonset",
    "ITIoffset",
]
OUTPUT_HEADER = [
    "onset",
    "duration",
    "trial_type",
    "response_time",
    "Offer",
    "IsFairBlock",
]
BLOCK_STARTS = {1, 9, 17, 25, 33, 41, 49, 57, 65}
PARTNERS = {1: "computer", 2: "ingroup", 3: "outgroup"}
RESPONSES = {2: "reject", 3: "accept"}


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
    boundaries = [(1, 73), (74, len(rows))]
    for session_number, (start, stop) in enumerate(boundaries, start=1):
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

        fair = _as_int(record["IsFairBlock"], "IsFairBlock")
        offer = _as_int(record["Offer"], "Offer")
        partner_code = _as_int(record["Partner"], "Partner")
        response = _as_int(record["resp"], "resp")
        if fair not in {0, 1}:
            raise ValueError(f"trial {trial}: invalid IsFairBlock value {fair}")
        if partner_code not in PARTNERS:
            raise ValueError(f"trial {trial}: invalid Partner value {partner_code}")
        if response not in {*RESPONSES, 999}:
            raise ValueError(f"trial {trial}: invalid response value {response}")

        onset = _format_float(record["decision_onset"])
        duration = _format_float(record["trialDuration"])
        partner = PARTNERS[partner_code]
        condition = f"{partner}_{'fair' if fair else 'unfair'}"

        if response == 999:
            output.append([onset, duration, "missed_trial", "n/a", str(offer), str(fair)])
        else:
            rt = _format_float(record["rt"])
            output.append(
                [onset, duration, f"event_{RESPONSES[response]}_{partner}", rt, str(offer), str(fair)]
            )
            output.append([onset, duration, f"event_{partner}", rt, str(offer), str(fair)])

        if trial in BLOCK_STARTS:
            output.append([onset, "33.500000", f"block_{condition}", "n/a", "n/a", "n/a"])
        elif response != 999:
            output.append([onset, "0", "event_RT", _format_float(record["rt"]), str(offer), str(fair)])
    return output


def render_tsv(rows: Iterable[Sequence[str]]) -> str:
    lines = ["\t".join(OUTPUT_HEADER)]
    lines.extend("\t".join(row) for row in rows)
    return "\n".join(lines) + "\n"


def target_paths(repo_root: Path, run: int) -> list[Path]:
    filename = f"sub-144_task-ultimatum_run-{run:02d}_events.tsv"
    return [
        repo_root / "bids" / "sub-144" / "func" / filename,
        repo_root / "derivatives" / "behavioraldata" / filename,
        repo_root / "code" / "behavioral_analyses" / filename,
    ]


def rebuild(repo_root: Path, check: bool = False) -> int:
    changed: list[Path] = []
    for raw_run in (0, 1):
        raw_path = (
            repo_root
            / "stimuli"
            / "psychopy"
            / "logs"
            / "144"
            / f"sub-144_task-ultimatum_run-{raw_run}_raw.csv"
        )
        sessions = read_logged_sessions(raw_path)
        rendered = render_tsv(make_event_rows(sessions[1]))
        for target in target_paths(repo_root, raw_run + 1):
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
        print("PASS: all tracked sub-144 Ultimatum event files match raw session 2")
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
