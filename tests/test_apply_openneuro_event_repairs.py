import hashlib
import importlib.util
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "code" / "apply_openneuro_event_repairs.py"
SPEC = importlib.util.spec_from_file_location("apply_openneuro_repairs", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ApplyOpenNeuroEventRepairsTests(unittest.TestCase):
    def make_dataset(self, root: Path) -> Path:
        dataset = root / "dataset"
        dataset.mkdir()
        (dataset / "dataset_description.json").write_text("{}\n")
        for repair in MODULE.REPAIRS:
            if not repair.required:
                continue
            destination = dataset / repair.destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = REPO_ROOT / repair.source
            destination.write_bytes(source.read_bytes())
        return dataset

    def test_preview_accepts_already_corrected_required_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = self.make_dataset(Path(temporary))
            self.assertEqual(MODULE.run(REPO_ROOT, dataset, None, False), 0)

    def test_unexpected_destination_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = self.make_dataset(Path(temporary))
            target = dataset / MODULE.REPAIRS[0].destination
            target.write_text("unexpected\n")
            self.assertEqual(MODULE.run(REPO_ROOT, dataset, None, False), 1)
            self.assertEqual(target.read_text(), "unexpected\n")

    def test_apply_backs_up_and_replaces_published_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "dataset"
            dataset.mkdir()
            (dataset / "dataset_description.json").write_text("{}\n")
            published = b"published version\n"
            repair = replace(
                MODULE.REPAIRS[0],
                published_sha256=hashlib.sha256(published).hexdigest(),
            )
            target = dataset / repair.destination
            target.parent.mkdir(parents=True)
            target.write_bytes(published)

            backup = root / "backup"
            original_repairs = MODULE.REPAIRS
            MODULE.REPAIRS = (repair,)
            try:
                self.assertEqual(MODULE.run(REPO_ROOT, dataset, backup, True), 0)
                self.assertEqual(
                    MODULE.sha256(target), MODULE.sha256(REPO_ROOT / repair.source)
                )
                self.assertEqual(
                    MODULE.sha256(backup / "originals" / repair.destination),
                    repair.published_sha256,
                )
                self.assertTrue((backup / "event-repair-manifest.tsv").is_file())
            finally:
                MODULE.REPAIRS = original_repairs


if __name__ == "__main__":
    unittest.main()
