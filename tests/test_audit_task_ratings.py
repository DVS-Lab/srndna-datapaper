import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "code/audit_task_ratings.py"
SPEC = importlib.util.spec_from_file_location("audit_task_ratings", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def ratings_block(traits, offset=0):
    header = "TrialNumber,Partner,Trait,ran,order,Rating\n"
    rows = []
    trial = 0
    for trait in traits:
        for partner in (3, 2, 1):
            trial += 1
            rows.append(f"{trial},{partner},{trait},1.0,{trial - 1}.0,{5 + offset}.0\n")
    return header + "".join(rows)


class AuditTaskRatingsTests(unittest.TestCase):
    def test_repeated_blocks_are_preserved_and_flagged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / "logs/104"
            logs.mkdir(parents=True)
            source = logs / "sub104_Bargaining-Ratings-2.csv"
            source.write_text(
                ratings_block((2, 1, 0, 4)) + ratings_block((2, 1, 0, 4), -1)
            )
            participants = root / "participants.tsv"
            participants.write_text("participant_id\tage\nsub-104\t20\n")

            files, normalized, coverage, repeated = MODULE.audit(logs.parent, participants)
            self.assertEqual(files[0]["n_blocks"], 2)
            self.assertEqual(len(normalized), 24)
            post = next(
                row
                for row in coverage
                if row["task"] == "ultimatum" and row["timepoint"] == "post"
            )
            self.assertEqual(post["status"], "multiple_blocks_needs_review")
            self.assertEqual(repeated[0]["changed_cells_between_blocks"], 12)
            self.assertEqual(repeated[0]["maximum_absolute_change"], "1")

    def test_sharedreward_session_one_is_unresolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / "logs/104"
            logs.mkdir(parents=True)
            (logs / "sub104_SR-Ratings-1.csv").write_text(ratings_block((0, 1), -5))
            participants = root / "participants.tsv"
            participants.write_text("participant_id\nsub-104\n")
            files, normalized, coverage, repeated = MODULE.audit(logs.parent, participants)
            self.assertEqual(files[0]["timepoint"], "unresolved")
            self.assertIn("protocol_status_unresolved", files[0]["problems"])
            self.assertEqual(normalized[0]["timepoint"], "unresolved")
            self.assertIn("source_script_missing", repeated[0]["review_reason"])
            sharedreward = next(
                row for row in coverage if row["task"] == "sharedreward"
            )
            self.assertEqual(sharedreward["status"], "missing")

    def test_cli_writes_four_audit_tables(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logs = root / "logs/104"
            logs.mkdir(parents=True)
            (logs / "sub104_Investment-Ratings-1.csv").write_text(
                ratings_block((2, 1, 0))
            )
            participants = root / "participants.tsv"
            participants.write_text("participant_id\nsub-104\n")
            output = root / "output"
            self.assertEqual(
                MODULE.main(
                    [
                        "--ratings-root",
                        str(logs.parent),
                        "--participants",
                        str(participants),
                        "--output-root",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertEqual(len(list(output.glob("*.tsv"))), 4)
            with (output / "ratings_normalized_rows.tsv").open(newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(len(rows), 9)


if __name__ == "__main__":
    unittest.main()
