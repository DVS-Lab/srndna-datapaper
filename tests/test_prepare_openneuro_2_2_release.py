import csv
import collections
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "code/prepare_openneuro_2_2_release.py"
SPEC = importlib.util.spec_from_file_location("prepare_openneuro_2_2_release", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def touch(path: Path, content: bytes = b"test\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class PrepareOpenNeuroReleaseTests(unittest.TestCase):
    def make_fixture(self, root: Path):
        repo = root / "repo"
        dataset = root / "dataset"
        touch(dataset / "dataset_description.json", b"{}\n")
        for relative in MODULE.ROOT_METADATA + MODULE.BEHAVIOR_SIDECARS:
            touch(repo / "bids" / relative)
        for relative in MODULE.EVENT_REPAIRS:
            touch(repo / "bids" / relative)
        for relative in MODULE.REPRODUCIBILITY_FILES:
            touch(repo / relative)
        rating = repo / "bids/sub-104/beh/sub-104_task-trust_acq-pre_beh.tsv"
        touch(rating)
        manifest = repo / "results/ratings_audit/ratings_bids_export_manifest.tsv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("participant_id", "destination", "sha256"),
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "participant_id": "sub-104",
                    "destination": rating.relative_to(repo / "bids").as_posix(),
                    "sha256": MODULE.sha256(rating),
                }
            )
        for run in ("01", "02"):
            touch(
                dataset
                / "derivatives/single_trials/sub-104"
                / f"sub-104_task-trust_run-{run}_singletrial-Act.nii.gz"
            )
        for relative in MODULE.SUB144_SINGLE_TRIALS:
            touch(dataset / relative)
        return repo, dataset

    def test_plan_has_only_four_sub144_event_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, dataset = self.make_fixture(Path(temporary))
            plan = MODULE.make_release_plan(
                repo, dataset, expected_ratings=1, expected_trust_images=2
            )
            events = sorted(
                item.destination.as_posix()
                for item in plan
                if item.destination.as_posix().startswith("sub-")
                and item.destination.as_posix().endswith("_events.tsv")
            )
            self.assertEqual(events, sorted(MODULE.EVENT_REPAIRS))
            self.assertFalse(any("task-trust" in event for event in events))

    def test_materialization_refuses_existing_staging_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, dataset = self.make_fixture(root)
            plan = MODULE.make_release_plan(
                repo, dataset, expected_ratings=1, expected_trust_images=2
            )
            staging = root / "staging"
            staging.mkdir()
            with self.assertRaises(FileExistsError):
                MODULE.materialize(plan, staging, copy_large_files=True)

    def test_materialization_checks_rating_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, dataset = self.make_fixture(root)
            plan = MODULE.make_release_plan(
                repo, dataset, expected_ratings=1, expected_trust_images=2
            )
            rating = repo / "bids/sub-104/beh/sub-104_task-trust_acq-pre_beh.tsv"
            rating.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.materialize(plan, root / "staging", copy_large_files=True)

    def test_tracked_release_contract_has_expected_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = Path(temporary) / "dataset"
            touch(dataset / "dataset_description.json", b"{}\n")
            for index in range(218):
                participant = f"sub-{index + 1:03d}"
                touch(
                    dataset
                    / "derivatives/single_trials"
                    / participant
                    / (
                        f"{participant}_task-trust_run-01_"
                        "singletrial-Act.nii.gz"
                    )
                )
            for relative in MODULE.SUB144_SINGLE_TRIALS:
                touch(dataset / relative)

            plan = MODULE.make_release_plan(ROOT, dataset)
            counts = collections.Counter(item.category for item in plan)

            self.assertEqual(len(plan), 481)
            self.assertEqual(counts["behavior_tsv"], 220)
            self.assertEqual(counts["single_trial_trust"], 218)
            self.assertEqual(counts["single_trial_sub144"], 4)
            self.assertEqual(counts["event_repair"], 4)

    def test_reproducibility_inputs_are_git_tracked(self):
        tracked = set(
            subprocess.check_output(
                ["git", "ls-files"], cwd=ROOT, text=True
            ).splitlines()
        )
        self.assertTrue(set(MODULE.REPRODUCIBILITY_FILES) <= tracked)


if __name__ == "__main__":
    unittest.main()
