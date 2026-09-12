import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "code/export_task_ratings_to_bids.py"
SPEC = importlib.util.spec_from_file_location("export_task_ratings_to_bids", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def normalized_rows(task, timepoint, session, block, offset=0):
    expected = MODULE.EXPECTED_CELLS[(task, timepoint)]
    rows = []
    for trial, (partner, dimension) in enumerate(sorted(expected), 1):
        rows.append(
            {
                "participant_id": "sub-104",
                "included_in_participants": "true",
                "task": task,
                "timepoint": timepoint,
                "source_session": str(session),
                "source_block": str(block),
                "source_file": f"source-{session}.csv",
                "trial_number": str(trial),
                "partner_code": "1",
                "partner": partner,
                "trait_code": "1",
                "rating_dimension": dimension,
                "response": str(5 + offset),
                "scale_min": "0",
                "scale_max": "10",
            }
        )
    return rows


def write_normalized(path, rows):
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class ExportTaskRatingsToBidsTests(unittest.TestCase):
    def test_final_complete_attempt_is_exported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normalized = root / "ratings.tsv"
            rows = normalized_rows("ultimatum", "pre", 1, 1)
            rows += normalized_rows("ultimatum", "pre", 1, 2, offset=2)
            write_normalized(normalized, rows)
            bids = root / "bids"
            manifest_path = root / "manifest.tsv"

            manifest = MODULE.export(normalized, bids, manifest_path)

            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]["source_block"], 2)
            output = bids / manifest[0]["destination"]
            with output.open(newline="") as stream:
                exported = list(csv.DictReader(stream, delimiter="\t"))
            self.assertTrue(exported)
            self.assertEqual({row["response"] for row in exported}, {"7"})

    def test_sharedreward_second_set_and_final_block_are_exported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normalized = root / "ratings.tsv"
            rows = normalized_rows("sharedreward", "post", 1, 1, offset=-2)
            rows += normalized_rows("sharedreward", "post", 2, 1, offset=-1)
            rows += normalized_rows("sharedreward", "post", 2, 2, offset=0)
            write_normalized(normalized, rows)
            bids = root / "bids"

            manifest = MODULE.export(normalized, bids, root / "manifest.tsv")

            self.assertEqual(manifest[0]["source_session"], 2)
            self.assertEqual(manifest[0]["source_block"], 2)
            with (bids / manifest[0]["destination"]).open(newline="") as stream:
                exported = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual({row["response"] for row in exported}, {"5"})

    def test_sidecars_document_columns_and_selection_rule(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normalized = root / "ratings.tsv"
            write_normalized(
                normalized,
                normalized_rows("trust", "pre", 1, 1),
            )
            bids = root / "bids"

            MODULE.export(normalized, bids, root / "manifest.tsv")

            for task in MODULE.TASK_METADATA:
                sidecar = json.loads((bids / f"task-{task}_beh.json").read_text())
                self.assertEqual(sidecar["TaskName"], task)
                self.assertIn("AcquisitionSelectionRule", sidecar)
                self.assertEqual(
                    {"trial_number", "partner", "rating_dimension", "response"},
                    {
                        key
                        for key in sidecar
                        if key
                        in {"trial_number", "partner", "rating_dimension", "response"}
                    },
                )

    def test_tracked_export_contract(self):
        manifest_path = ROOT / "results/ratings_audit/ratings_bids_export_manifest.tsv"
        with manifest_path.open(newline="", encoding="utf-8") as stream:
            manifest = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(manifest), 220)
        self.assertEqual(
            {task: sum(row["task"] == task for row in manifest) for task in MODULE.TASK_METADATA},
            {"ultimatum": 90, "trust": 91, "sharedreward": 39},
        )
        self.assertFalse(any(row["participant_id"] == "sub-143" for row in manifest))
        sub144 = [row for row in manifest if row["participant_id"] == "sub-144"]
        self.assertEqual(len(sub144), 5)
        self.assertTrue(all(int(row["source_block"]) == 2 for row in sub144))
        for row in manifest:
            path = ROOT / "bids" / row["destination"]
            self.assertTrue(path.is_file())
            self.assertEqual(MODULE.sha256(path), row["sha256"])


if __name__ == "__main__":
    unittest.main()
