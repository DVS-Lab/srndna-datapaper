#!/usr/bin/env python3
"""Export audited task ratings as subject-level BIDS behavioral recordings."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CELLS = {
    ("ultimatum", "pre"): {
        (partner, dimension)
        for partner in ("computer", "dissimilar", "similar")
        for dimension in ("fairness", "likeability")
    },
    ("ultimatum", "post"): {
        (partner, dimension)
        for partner in ("computer", "dissimilar", "similar")
        for dimension in ("anger", "fairness", "likeability", "satisfaction")
    },
    ("trust", "pre"): {
        (partner, dimension)
        for partner in ("computer", "stranger", "friend")
        for dimension in ("approachability", "likeability", "trustworthiness")
    },
    ("trust", "post"): {
        (partner, dimension)
        for partner in ("computer", "stranger", "friend")
        for dimension in ("approachability", "likeability", "trustworthiness")
    },
    ("sharedreward", "post"): {
        (partner, dimension)
        for partner in ("computer", "stranger", "friend")
        for dimension in ("win", "loss")
    },
}

TASK_METADATA = {
    "ultimatum": {
        "TaskName": "ultimatum",
        "TaskDescription": "Ratings of partners in the Ultimatum Game task.",
        "partner_levels": {
            "computer": "Computer partner",
            "dissimilar": "Human partner described as dissimilar to the participant",
            "similar": "Human partner described as similar to the participant",
        },
        "dimension_levels": {
            "anger": "Anger toward the partner",
            "fairness": "Perceived fairness of the partner",
            "likeability": "Perceived likeability of the partner",
            "satisfaction": "Satisfaction with the partner",
        },
        "minimum": 0,
        "maximum": 10,
    },
    "trust": {
        "TaskName": "trust",
        "TaskDescription": "Ratings of partners in the Trust task.",
        "partner_levels": {
            "computer": "Computer partner",
            "stranger": "Unfamiliar human partner",
            "friend": "Familiar human partner",
        },
        "dimension_levels": {
            "approachability": "Perceived approachability of the partner",
            "likeability": "Perceived likeability of the partner",
            "trustworthiness": "Perceived trustworthiness of the partner",
        },
        "minimum": 0,
        "maximum": 10,
    },
    "sharedreward": {
        "TaskName": "sharedreward",
        "TaskDescription": "Post-task partner-by-outcome ratings from the Shared Reward task.",
        "partner_levels": {
            "computer": "Computer partner",
            "stranger": "Unfamiliar human partner",
            "friend": "Familiar human partner",
        },
        "dimension_levels": {
            "win": "Rating associated with winning with the partner",
            "loss": "Rating associated with losing with the partner",
        },
        "minimum": -5,
        "maximum": 5,
    },
}

SELECTION_RULE = (
    "When ratings were acquired more than once for the same participant, task, "
    "and pre/post timepoint, the final complete attempt is the version of record."
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--normalized",
        type=Path,
        default=ROOT / "results/ratings_audit/ratings_normalized_rows.tsv",
    )
    parser.add_argument("--bids-root", type=Path, default=ROOT / "bids")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "results/ratings_audit/ratings_bids_export_manifest.tsv",
    )
    return parser.parse_args(argv)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def complete_attempt(rows: list[dict[str, str]]) -> bool:
    task = rows[0]["task"]
    timepoint = rows[0]["timepoint"]
    expected = EXPECTED_CELLS[(task, timepoint)]
    cells = Counter((row["partner"], row["rating_dimension"]) for row in rows)
    return set(cells) == expected and all(count == 1 for count in cells.values())


def select_versions(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    included = [row for row in rows if row["included_in_participants"] == "true"]
    grouped: defaultdict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in included:
        key = (row["participant_id"], row["task"], row["timepoint"])
        if (row["task"], row["timepoint"]) not in EXPECTED_CELLS:
            raise ValueError(f"unexpected task/timepoint: {row['task']}/{row['timepoint']}")
        grouped[key].append(row)

    selected: list[dict[str, object]] = []
    for (participant, task, timepoint), group in sorted(grouped.items()):
        attempts: defaultdict[tuple[int, str, int], list[dict[str, str]]] = defaultdict(list)
        for row in group:
            attempt = (
                int(row["source_session"]),
                row["source_file"],
                int(row["source_block"]),
            )
            attempts[attempt].append(row)
        complete = [attempt for attempt, values in attempts.items() if complete_attempt(values)]
        if not complete:
            raise ValueError(
                f"no complete ratings attempt for {participant} {task} {timepoint}"
            )
        source_session, source_file, source_block = max(complete)
        values = sorted(
            attempts[(source_session, source_file, source_block)],
            key=lambda row: int(row["trial_number"]),
        )
        selected.append(
            {
                "participant_id": participant,
                "task": task,
                "timepoint": timepoint,
                "source_session": source_session,
                "source_block": source_block,
                "source_file": source_file,
                "rows": values,
            }
        )
    return selected


def sidecar(task: str) -> dict[str, object]:
    metadata = TASK_METADATA[task]
    return {
        "TaskName": metadata["TaskName"],
        "TaskDescription": metadata["TaskDescription"],
        "AcquisitionLabels": {
            "pre": "Ratings acquired before the associated task",
            "post": "Ratings acquired after the associated task",
        },
        "AcquisitionSelectionRule": SELECTION_RULE,
        "trial_number": {
            "Description": "Presentation order within the retained rating attempt."
        },
        "partner": {
            "Description": "Partner evaluated by the participant.",
            "Levels": metadata["partner_levels"],
        },
        "rating_dimension": {
            "Description": "Attribute or outcome evaluated for the partner.",
            "Levels": metadata["dimension_levels"],
        },
        "response": {
            "Description": "Participant rating response.",
            "Units": "rating scale points",
            "Minimum": metadata["minimum"],
            "Maximum": metadata["maximum"],
        },
    }


def export(
    normalized_path: Path, bids_root: Path, manifest_path: Path
) -> list[dict[str, object]]:
    selected = select_versions(read_tsv(normalized_path))
    manifest: list[dict[str, object]] = []
    for record in selected:
        participant = str(record["participant_id"])
        task = str(record["task"])
        timepoint = str(record["timepoint"])
        destination = (
            bids_root
            / participant
            / "beh"
            / f"{participant}_task-{task}_acq-{timepoint}_beh.tsv"
        )
        output_rows = [
            {
                "trial_number": row["trial_number"],
                "partner": row["partner"],
                "rating_dimension": row["rating_dimension"],
                "response": row["response"],
            }
            for row in record["rows"]
        ]
        write_tsv(
            destination,
            ("trial_number", "partner", "rating_dimension", "response"),
            output_rows,
        )
        manifest.append(
            {
                **{key: record[key] for key in (
                    "participant_id",
                    "task",
                    "timepoint",
                    "source_session",
                    "source_block",
                    "source_file",
                )},
                "destination": destination.relative_to(bids_root).as_posix(),
                "n_rows": len(output_rows),
                "sha256": sha256(destination),
                "selection_rule": "final_complete_attempt",
            }
        )

    for task in sorted(TASK_METADATA):
        path = bids_root / f"task-{task}_beh.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as stream:
            json.dump(sidecar(task), stream, indent=2, ensure_ascii=False)
            stream.write("\n")

    write_tsv(
        manifest_path,
        (
            "participant_id",
            "task",
            "timepoint",
            "source_session",
            "source_block",
            "source_file",
            "destination",
            "n_rows",
            "sha256",
            "selection_rule",
        ),
        manifest,
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = export(
            args.normalized.resolve(), args.bids_root.resolve(), args.manifest.resolve()
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    counts = Counter(str(row["task"]) for row in manifest)
    print(
        "PASS: exported "
        f"{len(manifest)} task-rating acquisitions "
        + ", ".join(f"{task}={counts[task]}" for task in sorted(counts))
    )
    print(f"BIDS root: {args.bids_root.resolve()}")
    print(f"Manifest: {args.manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
