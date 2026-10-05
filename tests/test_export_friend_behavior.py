import csv
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import export_friend_behavior as export


class FriendBehaviorTests(unittest.TestCase):
    def source_rows(self, task):
        path = ROOT / f"stimuli/psychopy/logs/204/sub-204_task-{task}_run-0_raw.csv"
        return export.read_segments(path, task)[0]

    def test_one_row_per_source_trial_and_block_first_rt(self):
        rows = self.source_rows("ultimatum")
        output = export.convert(rows, "ultimatum")
        self.assertEqual(len(output), 72)
        for raw, out in zip(rows, output):
            self.assertEqual(out["decision_onset_time"], raw["decision_onset"])
            if float(raw["resp"]) != 999:
                self.assertEqual(out["response_time"], raw["rt"])
        self.assertEqual(output[0]["response"], "n/a")
        self.assertEqual(output[0]["response_time"], "n/a")

    def test_zero_investment_is_not_missing(self):
        output = export.convert(self.source_rows("trust"), "trust")
        self.assertEqual(len(output), 36)
        self.assertEqual(output[0]["investment"], 0)
        self.assertEqual(output[0]["response_recorded"], "true")

    def test_restart_and_invalid_choice_are_rejected(self):
        rows = self.source_rows("trust")
        rows[1]["TrialNumber"] = "1"
        with self.assertRaisesRegex(ValueError, "trial numbers"):
            export.convert(rows, "trust")
        rows = self.source_rows("trust")
        rows[0]["resp"] = "7"
        with self.assertRaisesRegex(ValueError, "investment inconsistent"):
            export.convert(rows, "trust")

    def test_audit_does_not_silently_select_an_acquisition(self):
        payloads, audit, subjects = export.build(ROOT)
        self.assertEqual(len(subjects), 48)
        self.assertEqual(len(audit), 301)
        unresolved = [r for r in audit if r["status"].startswith("needs_")]
        self.assertEqual(len(unresolved), 11)
        self.assertEqual(len(payloads), 290)
        self.assertTrue(all(not r["destination"] for r in unresolved))
        row = next(r for r in audit if r["participant_id"] == "sub-244" and r["task"] == "trust" and r["run"] == "01")
        self.assertEqual(row["segment_lengths"], "36,36")
        self.assertEqual(row["segment_other_owners"], "1:243;2:")
        for row in audit:
            if row["destination"]:
                data = payloads[row["destination"]]
                self.assertEqual(export.sha(data), row["sha256"])
                self.assertEqual(data.count(b"\n") - 1, row["trials"])

    def test_sidecars_cover_exported_columns(self):
        for task, fields in export.FIELDS.items():
            doc = json.loads((ROOT / f"supplementary/friend_behavior/task-{task}_acq-game_beh.json").read_text())
            self.assertTrue(set(fields) <= set(doc))
            self.assertNotIn("onset", fields)
            self.assertNotIn("duration", fields)
            self.assertTrue(doc["CogAtlasID"])
        for task in ("trust", "ultimatum", "sharedreward"):
            doc = json.loads((ROOT / f"bids/task-{task}_beh.json").read_text())
            self.assertNotIn("CogAtlasID", doc)
            self.assertNotIn("CogPOID", doc)

    def test_participants_preserve_known_demographics(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "bids").mkdir()
            (repo / "bids/participants.tsv").write_text("participant_id\tage\tsex\tgroup\nsub-104\t20\tM\tcontrol\n")
            before = (repo / "bids/participants.tsv").read_bytes()
            destination = "supplementary/friend_behavior/sub-204/beh/sub-204_task-trust_acq-game_run-01_beh.tsv"
            audit = [{"status": "ready", "trials": 1}]
            with patch.object(sys, "argv", ["export", "--repository-root", str(repo), "--write"]), patch.object(export, "build", return_value=({destination: b"trial_number\n1\n"}, audit, ["sub-204"])):
                self.assertEqual(export.main(), 0)
            self.assertEqual(before, (repo / "bids/participants.tsv").read_bytes())
            self.assertTrue((repo / destination).is_file())
            self.assertFalse((repo / "bids/sub-204").exists())

    def test_primary_inventory_stays_at_fifty(self):
        with (ROOT / "bids/participants.tsv").open() as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(rows), 50)
        self.assertTrue(all(row["participant_id"].startswith("sub-1") for row in rows))
        self.assertIn("sub-2*", (ROOT / "bids/.bidsignore").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
