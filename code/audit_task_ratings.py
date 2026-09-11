#!/usr/bin/env python3
"""Audit PsychoPy partner ratings before converting them to BIDS behavioral data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
FILENAME = re.compile(
    r"^sub-?(?P<subject>[0-9]+)_(?P<family>Bargaining|Investment|SR)"
    r"-Ratings-(?P<session>[0-9]*)\.csv$"
)


@dataclass(frozen=True)
class RatingSpec:
    task: str
    partner_levels: dict[int, str]
    dimension_levels: dict[int, str]
    sessions: dict[str, str]
    expected_sessions: tuple[str, ...]
    scale_min: int
    scale_max: int

    def expected_cells(self, session: str) -> set[tuple[int, int]]:
        dimensions = set(self.dimension_levels)
        if self.task == "ultimatum" and session == "1":
            dimensions = {1, 2}
        return {
            (partner, dimension)
            for partner in self.partner_levels
            for dimension in dimensions
        }


SPECS = {
    "Bargaining": RatingSpec(
        task="ultimatum",
        partner_levels={1: "computer", 2: "dissimilar", 3: "similar"},
        dimension_levels={
            0: "anger",
            1: "likeability",
            2: "fairness",
            4: "satisfaction",
        },
        sessions={"1": "pre", "2": "post"},
        expected_sessions=("1", "2"),
        scale_min=0,
        scale_max=10,
    ),
    "Investment": RatingSpec(
        task="trust",
        partner_levels={1: "computer", 2: "stranger", 3: "friend"},
        dimension_levels={
            0: "approachability",
            1: "likeability",
            2: "trustworthiness",
        },
        sessions={"1": "pre", "2": "post"},
        expected_sessions=("1", "2"),
        scale_min=0,
        scale_max=10,
    ),
    "SR": RatingSpec(
        task="sharedreward",
        partner_levels={1: "computer", 2: "stranger", 3: "friend"},
        dimension_levels={0: "win", 1: "loss"},
        # The historical SR_postRatings.py generator identifies the entered
        # session as Pre/Post, but only session 2 was used protocol-wide. When a
        # second SR set exists, the study decision rule retains it and excludes
        # the first set.
        sessions={"1": "post", "2": "post"},
        expected_sessions=("2",),
        scale_min=-5,
        scale_max=5,
    ),
}

REQUIRED_COLUMNS = {"TrialNumber", "Partner", "Trait", "Rating"}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ratings-root",
        type=Path,
        default=ROOT / "stimuli/psychopy/logs",
    )
    parser.add_argument(
        "--participants",
        type=Path,
        default=ROOT / "bids/participants.tsv",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "results/ratings_audit",
    )
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def load_participants(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows or "participant_id" not in rows[0]:
        raise ValueError("participants table lacks participant_id")
    participants = {row["participant_id"].removeprefix("sub-") for row in rows}
    if "" in participants or len(participants) != len(rows):
        raise ValueError("participants table contains blank or duplicate participant_id")
    return participants


def integer(value: str, label: str) -> int:
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"invalid {label}: {value!r}")
    return int(number)


def number(value: str, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"invalid {label}: {value!r}")
    return result


def split_blocks(path: Path) -> list[tuple[list[str], list[list[str]]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    blocks: list[tuple[list[str], list[list[str]]]] = []
    header: list[str] | None = None
    body: list[list[str]] = []
    for row in rows:
        is_header = bool(row) and row[0].strip().casefold() == "trialnumber"
        if is_header:
            if header is not None:
                blocks.append((header, body))
            header = [cell.strip() for cell in row]
            body = []
        elif any(cell.strip() for cell in row):
            if header is None:
                raise ValueError("data row precedes the first CSV header")
            body.append(row)
    if header is not None:
        blocks.append((header, body))
    if not blocks:
        raise ValueError("no rating blocks found")
    return blocks


def audit_block(
    header: list[str], rows: list[list[str]], spec: RatingSpec, session: str
) -> tuple[list[dict[str, object]], list[str]]:
    problems: list[str] = []
    if not REQUIRED_COLUMNS.issubset(header):
        missing = sorted(REQUIRED_COLUMNS - set(header))
        return [], ["missing_columns:" + ",".join(missing)]
    positions = {name: header.index(name) for name in REQUIRED_COLUMNS}
    expected = spec.expected_cells(session)
    records: list[dict[str, object]] = []
    cells: Counter[tuple[int, int]] = Counter()
    for row_number, row in enumerate(rows, 1):
        try:
            if len(row) != len(header):
                raise ValueError(f"expected {len(header)} columns; found {len(row)}")
            trial = integer(row[positions["TrialNumber"]], "TrialNumber")
            partner = integer(row[positions["Partner"]], "Partner")
            dimension = integer(row[positions["Trait"]], "Trait")
            response = number(row[positions["Rating"]], "Rating")
        except (TypeError, ValueError) as error:
            problems.append(f"row_{row_number}:{error}")
            continue
        cell = (partner, dimension)
        cells[cell] += 1
        if partner not in spec.partner_levels:
            problems.append(f"row_{row_number}:unexpected_partner:{partner}")
        if dimension not in spec.dimension_levels:
            problems.append(f"row_{row_number}:unexpected_trait:{dimension}")
        if not spec.scale_min <= response <= spec.scale_max:
            problems.append(f"row_{row_number}:rating_out_of_range:{response:g}")
        records.append(
            {
                "trial_number": trial,
                "partner_code": partner,
                "partner": spec.partner_levels.get(partner, "unresolved"),
                "trait_code": dimension,
                "rating_dimension": spec.dimension_levels.get(
                    dimension, "unresolved"
                ),
                "response": f"{response:g}",
                "scale_min": spec.scale_min,
                "scale_max": spec.scale_max,
            }
        )
    observed = set(cells)
    missing_cells = sorted(expected - observed)
    unexpected_cells = sorted(observed - expected)
    repeated_cells = sorted(cell for cell, count in cells.items() if count > 1)
    if missing_cells:
        problems.append(
            "missing_cells:" + ",".join(f"{p}-{t}" for p, t in missing_cells)
        )
    if unexpected_cells:
        problems.append(
            "unexpected_cells:"
            + ",".join(f"{p}-{t}" for p, t in unexpected_cells)
        )
    if repeated_cells:
        problems.append(
            "repeated_cells:" + ",".join(f"{p}-{t}" for p, t in repeated_cells)
        )
    return records, problems


def write_tsv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=tuple(fields),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def directory_subject(path: Path) -> str:
    label = path.parent.name.removeprefix("sub-")
    return label if label.isdigit() else ""


def audit(
    ratings_root: Path, participants_path: Path
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    participants = load_participants(participants_path)
    files: list[dict[str, object]] = []
    normalized: list[dict[str, object]] = []
    repeat_review: list[dict[str, object]] = []
    sources: defaultdict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)

    candidates = sorted(
        path for path in ratings_root.rglob("*Ratings*.csv") if path.is_file()
    )
    recognized_candidate_keys = {
        (
            match.group("subject"),
            match.group("family"),
            match.group("session"),
        )
        for path in candidates
        if (match := FILENAME.match(path.name))
    }
    parsed_file_rows: list[dict[str, object]] = []
    for path in candidates:
        match = FILENAME.match(path.name)
        if not match:
            files.append(
                {
                    "participant_id": "n/a",
                    "included_in_participants": "false",
                    "source_file": relative(path),
                    "source_family": "unresolved",
                    "source_session": "unresolved",
                    "task": "unresolved",
                    "timepoint": "unresolved",
                    "file_sha256": sha256(path),
                    "file_bytes": path.stat().st_size,
                    "n_blocks": 0,
                    "block_row_counts": "n/a",
                    "exact_content_group_size": 1,
                    "exact_content_matches": "n/a",
                    "status": "review",
                    "problems": "unmatched_filename",
                }
            )
            continue
        subject = match.group("subject")
        family = match.group("family")
        session = match.group("session")
        spec = SPECS[family]
        problems: list[str] = []
        if directory_subject(path) != subject:
            problems.append(
                f"directory_subject_mismatch:{directory_subject(path) or 'unresolved'}"
            )
        if not session:
            problems.append("missing_source_session")
        if session not in spec.sessions:
            problems.append(f"unexpected_source_session:{session or 'blank'}")
        elif session not in spec.expected_sessions:
            if family == "SR" and session == "1":
                if (subject, family, "2") in recognized_candidate_keys:
                    problems.append("superseded_sharedreward_first_set")
                else:
                    problems.append("sharedreward_first_set_without_second_set")
            else:
                problems.append(f"protocol_status_unresolved_for_session:{session}")
        try:
            blocks = split_blocks(path)
        except ValueError as error:
            blocks = []
            problems.append(str(error))
        file_records: list[list[dict[str, object]]] = []
        block_problems: list[list[str]] = []
        for block_index, (header, rows) in enumerate(blocks, 1):
            records, issues = audit_block(header, rows, spec, session)
            file_records.append(records)
            block_problems.append(issues)
            for record in records:
                normalized.append(
                    {
                        "participant_id": f"sub-{subject}",
                        "included_in_participants": str(subject in participants).lower(),
                        "task": spec.task,
                        "timepoint": spec.sessions.get(session, "unresolved"),
                        "source_session": session or "unresolved",
                        "source_block": block_index,
                        "source_file": relative(path),
                        **record,
                    }
                )
        for block_index, issues in enumerate(block_problems, 1):
            problems.extend(f"block_{block_index}:{issue}" for issue in issues)
        if len(blocks) > 1:
            problems.append(f"multiple_acquisition_blocks:{len(blocks)}")
            changed = "n/a"
            maximum = "n/a"
            if len(file_records) == 2 and all(not issues for issues in block_problems):
                first = {
                    (row["partner_code"], row["trait_code"]): float(row["response"])
                    for row in file_records[0]
                }
                second = {
                    (row["partner_code"], row["trait_code"]): float(row["response"])
                    for row in file_records[1]
                }
                shared = sorted(set(first) & set(second))
                differences = [abs(second[cell] - first[cell]) for cell in shared]
                changed = sum(difference != 0 for difference in differences)
                maximum = f"{max(differences, default=0):g}"
            exact_duplicate = changed == 0
            if family == "SR":
                resolution = "retain_last_block"
                review_reason = "sharedreward_second_set_decision_rule"
            elif exact_duplicate:
                resolution = "collapse_exact_duplicate"
                review_reason = "exact_duplicate_acquisition_block"
            else:
                resolution = "unresolved"
                review_reason = "multiple_complete_acquisitions_in_one_source_file"
            repeat_review.append(
                {
                    "participant_id": f"sub-{subject}",
                    "task": spec.task,
                    "timepoint": spec.sessions.get(session, "unresolved"),
                    "source_file": relative(path),
                    "n_complete_blocks": sum(not issues for issues in block_problems),
                    "n_blocks": len(blocks),
                    "changed_cells_between_blocks": changed,
                    "maximum_absolute_change": maximum,
                    "resolution": resolution,
                    "review_reason": review_reason,
                }
            )
        if family == "SR" and session == "1":
            has_second_set = (subject, family, "2") in recognized_candidate_keys
            repeat_review.append(
                {
                    "participant_id": f"sub-{subject}",
                    "task": spec.task,
                    "timepoint": "post",
                    "source_file": relative(path),
                    "n_complete_blocks": sum(not issues for issues in block_problems),
                    "n_blocks": len(blocks),
                    "changed_cells_between_blocks": "n/a",
                    "maximum_absolute_change": "n/a",
                    "resolution": (
                        "exclude_superseded_first_set"
                        if has_second_set
                        else "unresolved"
                    ),
                    "review_reason": (
                        "sharedreward_second_set_decision_rule"
                        if has_second_set
                        else "sharedreward_first_set_without_second_set"
                    ),
                }
            )
        row = {
            "participant_id": f"sub-{subject}",
            "included_in_participants": str(subject in participants).lower(),
            "source_file": relative(path),
            "source_family": family,
            "source_session": session or "unresolved",
            "task": spec.task,
            "timepoint": spec.sessions.get(session, "unresolved"),
            "file_sha256": sha256(path),
            "file_bytes": path.stat().st_size,
            "n_blocks": len(blocks),
            "block_row_counts": ";".join(str(len(rows)) for _, rows in blocks),
            "exact_content_group_size": 1,
            "exact_content_matches": "n/a",
            "status": "review" if problems or len(blocks) > 1 else "complete",
            "problems": ";".join(problems) or "n/a",
        }
        files.append(row)
        parsed_file_rows.append(row)
        sources[(subject, family, session)].append(row)

    content_groups: defaultdict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in parsed_file_rows:
        content_groups[
            (str(row["source_family"]), str(row["source_session"]), str(row["file_sha256"]))
        ].append(row)
    for group in content_groups.values():
        if len(group) < 2:
            continue
        paths = sorted(str(row["source_file"]) for row in group)
        for row in group:
            row["exact_content_group_size"] = len(group)
            row["exact_content_matches"] = ";".join(
                path for path in paths if path != row["source_file"]
            )

    coverage: list[dict[str, object]] = []
    for subject in sorted(participants, key=int):
        for family, spec in SPECS.items():
            for session in spec.expected_sessions:
                matched = sources[(subject, family, session)]
                n_blocks = sum(int(row["n_blocks"]) for row in matched)
                if not matched:
                    status = "missing"
                elif len(matched) > 1:
                    status = "multiple_files"
                elif n_blocks > 1:
                    status = (
                        "resolved_last_block"
                        if spec.task == "sharedreward"
                        else "multiple_blocks_needs_review"
                    )
                elif matched[0]["status"] == "complete":
                    status = "complete"
                else:
                    status = "review"
                coverage.append(
                    {
                        "participant_id": f"sub-{subject}",
                        "task": spec.task,
                        "timepoint": spec.sessions[session],
                        "expected": "true",
                        "n_source_files": len(matched),
                        "n_blocks": n_blocks,
                        "source_files": ";".join(
                            str(row["source_file"]) for row in matched
                        ),
                        "status": status,
                    }
                )
    return files, normalized, coverage, repeat_review


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        files, normalized, coverage, repeat_review = audit(
            args.ratings_root.resolve(), args.participants.resolve()
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    write_tsv(
        args.output_root / "ratings_file_inventory.tsv",
        (
            "participant_id",
            "included_in_participants",
            "source_file",
            "source_family",
            "source_session",
            "task",
            "timepoint",
            "file_sha256",
            "file_bytes",
            "n_blocks",
            "block_row_counts",
            "exact_content_group_size",
            "exact_content_matches",
            "status",
            "problems",
        ),
        files,
    )
    write_tsv(
        args.output_root / "ratings_normalized_rows.tsv",
        (
            "participant_id",
            "included_in_participants",
            "task",
            "timepoint",
            "source_session",
            "source_block",
            "source_file",
            "trial_number",
            "partner_code",
            "partner",
            "trait_code",
            "rating_dimension",
            "response",
            "scale_min",
            "scale_max",
        ),
        normalized,
    )
    write_tsv(
        args.output_root / "ratings_subject_coverage.tsv",
        (
            "participant_id",
            "task",
            "timepoint",
            "expected",
            "n_source_files",
            "n_blocks",
            "source_files",
            "status",
        ),
        coverage,
    )
    write_tsv(
        args.output_root / "ratings_repeat_review.tsv",
        (
            "participant_id",
            "task",
            "timepoint",
            "source_file",
            "n_complete_blocks",
            "n_blocks",
            "changed_cells_between_blocks",
            "maximum_absolute_change",
            "resolution",
            "review_reason",
        ),
        repeat_review,
    )
    included_files = sum(row["included_in_participants"] == "true" for row in files)
    missing = sum(row["status"] == "missing" for row in coverage)
    repeated = sum(row["status"] == "multiple_blocks_needs_review" for row in coverage)
    print(f"Rating source files inventoried: {len(files)}")
    print(f"Files belonging to participants.tsv: {included_files}")
    print(f"Normalized rating rows: {len(normalized)}")
    print(f"Expected participant/task/timepoint cells missing: {missing}")
    print(f"Expected cells with multiple acquisition blocks: {repeated}")
    unresolved = sum(row["resolution"] == "unresolved" for row in repeat_review)
    print(f"Acquisition resolution records: {len(repeat_review)}")
    print(f"Unresolved acquisition items: {unresolved}")
    print(f"Audit tables: {args.output_root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
