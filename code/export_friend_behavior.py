#!/usr/bin/env python3
"""Export the previously published sub-2xx task runs from original trial logs.

Preview by default. --write materializes only unambiguous supplementary runs
outside bids/ and an audit; it never changes the primary participant inventory.
Concatenated acquisitions are reported, never silently selected or combined.
Source logs and historical event tables are never modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"trust": 36, "ultimatum": 72}
COMMON = ["trial_number", "partner", "response", "response_time",
          "response_recorded", "decision_onset_time", "response_onset_time"]
FIELDS = {
    "trust": COMMON + ["investment", "choice", "left_option", "right_option",
                       "reciprocate", "outcome_onset_time", "outcome_offset_time"],
    "ultimatum": COMMON + ["offer", "is_fair_block", "block_number",
                           "decision_offset_time", "trial_duration"],
}
REQUIRED = {
    "trust": {"TrialNumber", "Partner", "bpress", "resp", "rt", "onset",
              "resp_onset", "highlow", "cLeft", "cRight", "Reciprocate",
              "outcome_onset", "outcome_offset"},
    "ultimatum": {"TrialNumber", "Partner", "resp", "rt", "decision_onset",
                  "resp_onset", "Offer", "IsFairBlock", "Blockn",
                  "decision_offset", "trialDuration"},
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def table_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def read_segments(path: Path, task: str):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.reader(stream) if any(cell.strip() for cell in row)]
    if not rows or not REQUIRED[task].issubset(rows[0]):
        raise ValueError(f"missing required columns: {path}")
    header = rows[0]
    if len(header) != len(set(header)):
        raise ValueError(f"duplicate column names: {path}")
    segments = [[]]
    for row in rows[1:]:
        if row == header:
            segments.append([])
        elif len(row) != len(header):
            raise ValueError(f"malformed row: {path}")
        else:
            segments[-1].append(dict(zip(header, row)))
    return segments


def number(row, key, *, missing=False):
    value = row[key].strip()
    if missing and value.lower() in {"", "nan", "n/a", "999", "999.0"}:
        return "n/a"
    try:
        n = float(value)
    except ValueError as error:
        raise ValueError(f"invalid {key}: {value}") from error
    if not math.isfinite(n):
        raise ValueError(f"nonfinite {key}: {value}")
    return value


def integer(row, key, allowed=None):
    n = float(number(row, key))
    if not n.is_integer() or (allowed is not None and int(n) not in allowed):
        raise ValueError(f"invalid {key}: {n}")
    return int(n)


def convert(rows, task):
    if not 0 < len(rows) <= EXPECTED[task]:
        raise ValueError(f"unexpected trial count: {len(rows)} for {task}")
    output = []
    previous = -math.inf
    for trial, row in enumerate(rows, 1):
        if integer(row, "TrialNumber") != trial:
            raise ValueError("trial numbers must be consecutive from 1; possible unmarked restart")
        partner_code = integer(row, "Partner", {1, 2, 3})
        partner = ({1: "computer", 2: "stranger", 3: "friend"} if task == "trust"
                   else {1: "computer", 2: "similar", 3: "dissimilar"})[partner_code]
        onset_key = "onset" if task == "trust" else "decision_onset"
        onset = number(row, onset_key)
        if float(onset) < 0 or float(onset) <= previous:
            raise ValueError("non-increasing/negative decision onset")
        previous = float(onset)
        response_key = "bpress" if task == "trust" else "resp"
        button = integer(row, response_key, {2, 3, 999})
        missed = integer(row, "resp") == 999
        if (button == 999) != missed:
            raise ValueError("button and response disagree about missed trial")
        rt = number(row, "rt", missing=True)
        if not missed and (rt == "n/a" or float(rt) < 0):
            raise ValueError("recorded response has invalid RT")
        out = dict(trial_number=trial, partner=partner,
                   response="n/a" if missed else str(button),
                   response_time="n/a" if missed else rt,
                   response_recorded="false" if missed else "true",
                   decision_onset_time=onset,
                   response_onset_time="n/a" if missed else number(row, "resp_onset"))
        if task == "trust":
            left, right = integer(row, "cLeft", set(range(9))), integer(row, "cRight", set(range(9)))
            investment = integer(row, "resp", set(range(9)) | {999})
            choice = row["highlow"].strip()
            if not missed and (choice not in {"high", "low"} or investment !=
                               (max(left, right) if choice == "high" else min(left, right))):
                raise ValueError("investment inconsistent with high/low choice")
            out.update(investment="n/a" if missed else investment,
                       choice="n/a" if missed else choice, left_option=left, right_option=right,
                       reciprocate=integer(row, "Reciprocate", {0, 1}),
                       outcome_onset_time=number(row, "outcome_onset", missing=True),
                       outcome_offset_time=number(row, "outcome_offset", missing=True))
        else:
            out.update(response="n/a" if missed else {2: "reject", 3: "accept"}[button],
                       offer=integer(row, "Offer", set(range(21))),
                       is_fair_block=integer(row, "IsFairBlock", {0, 1}),
                       block_number=integer(row, "Blockn", set(range(1, 10))),
                       decision_offset_time=number(row, "decision_offset"),
                       trial_duration=number(row, "trialDuration"))
        output.append(out)
    return output


def build(repo: Path):
    payloads = {}
    audit = []
    subjects = sorted(p.name for p in (repo / "bids").glob("sub-2[0-9][0-9]") if p.is_dir())
    # Compare exact source records across owners, including source-only and test
    # directories. A copy under a second owner is an identity question, not
    # evidence that one owner is correct.
    owners = {}
    for source in sorted((repo / "stimuli/psychopy/logs").glob("*/*_raw.csv")):
        task = source.name.split("task-")[-1].split("_")[0]
        if task not in EXPECTED:
            continue
        try:
            segments = read_segments(source, task)
        except (ValueError, UnicodeError):
            continue
        for segment in segments:
            if segment:
                key = sha(json.dumps(segment, sort_keys=True).encode())
                owners.setdefault(key, set()).add(source.parent.name)
    for subject in subjects:
        for events in sorted((repo / "bids" / subject / "func").glob("*_events.tsv")):
            task = events.name.split("task-")[1].split("_")[0]
            if task not in EXPECTED:
                raise ValueError(f"unexpected friend task: {events}")
            run = int(events.name.split("run-")[1].split("_")[0])
            source = repo / "stimuli/psychopy/logs" / subject[4:] / f"{subject}_task-{task}_run-{run-1}_raw.csv"
            row = dict(participant_id=subject, task=task, run=f"{run:02d}",
                       source=source.relative_to(repo).as_posix(), source_sha256="",
                       legacy_events=events.relative_to(repo).as_posix(),
                       legacy_events_sha256=sha(events.read_bytes()),
                       segments=0, segment_lengths="", segment_other_owners="", trials=0, status="", detail="",
                       destination="", sha256="")
            try:
                row["source_sha256"] = sha(source.read_bytes())
                segments = read_segments(source, task)
                row.update(segments=len(segments), segment_lengths=",".join(str(len(s)) for s in segments))
                row["segment_other_owners"] = ";".join(
                    f"{i}:" + ",".join(sorted(owners.get(sha(json.dumps(s, sort_keys=True).encode()), set()) - {subject[4:]}))
                    for i, s in enumerate(segments, 1))
                if len(segments) != 1:
                    row.update(status="needs_identity_review", detail="multiple acquisitions; no selection made")
                else:
                    key = sha(json.dumps(segments[0], sort_keys=True).encode())
                    other = sorted(owners.get(key, set()) - {subject[4:]})
                    if other:
                        row.update(status="needs_identity_review",
                                   detail="identical acquisition under source directories: " + ",".join(other))
                        audit.append(row)
                        continue
                    trials = convert(segments[0], task)
                    relative = f"supplementary/friend_behavior/{subject}/beh/{subject}_task-{task}_acq-game_run-{run:02d}_beh.tsv"
                    data = table_bytes(trials, FIELDS[task])
                    payloads[relative] = data
                    row.update(trials=len(trials), status="ready" if len(trials) == EXPECTED[task] else "partial_run",
                               destination=relative, sha256=sha(data))
            except (OSError, ValueError) as error:
                row.update(status="needs_source_review", detail=str(error))
            audit.append(row)
    if not audit:
        raise ValueError("no published friend runs found")
    return payloads, audit, subjects


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repo = args.repository_root.resolve()
    payloads, audit, subjects = build(repo)
    unresolved = [r for r in audit if r["status"].startswith("needs_")]
    summary = dict(subjects=len(subjects), inventoried_runs=len(audit),
                   exported_runs=len(payloads), exported_trials=sum(r["trials"] for r in audit),
                   unresolved_runs=len(unresolved),
                   all_source_identities_resolved=not unresolved,
                   included_in_primary_release=False,
                   output_root="supplementary/friend_behavior",
                   scope="Previously published sub-2xx task runs only; no new subjects or ratings",
                   source_selection="No concatenated acquisition selected automatically")
    if args.write:
        from repair_openneuro_validation import atomic_write
        outputs = {repo / relative: data for relative, data in payloads.items()}
        # No overwrite of a divergent export, including all preflight checks before writing.
        for path, data in outputs.items():
            if path.is_symlink() or not path.resolve().is_relative_to((repo / "supplementary/friend_behavior").resolve()):
                raise ValueError(f"unsafe output path: {path}")
            if path.exists() and path.read_bytes() != data:
                raise ValueError(f"different export exists; review before replacing: {path}")
        for path, data in outputs.items():
            atomic_write(path, data)
        report = repo / "results/friend_behavior"
        report.mkdir(parents=True, exist_ok=True)
        atomic_write(report / "export_manifest.tsv", table_bytes(audit, list(audit[0])))
        atomic_write(report / "summary.json", (json.dumps(summary, indent=2) + "\n").encode())
    print(json.dumps(summary, indent=2))
    for row in unresolved:
        print(f"REVIEW: {row['participant_id']} {row['task']} run-{row['run']}: {row['detail']}")
    return 0  # An audit/export is not certification of participant identity.


if __name__ == "__main__":
    raise SystemExit(main())
