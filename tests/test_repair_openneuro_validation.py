import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("repair_validation", ROOT / "code/repair_openneuro_validation.py")
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)


def put(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def fixture(root):
    put(root, "dataset_description.json", '{"GeneratedBy":[{"Name":"conversion"}]}')
    put(root, "participants.tsv", "participant_id\nsub-134\nsub-138\n")
    put(root, "README", "Test release\n")
    put(root, "CHANGES", "2.2.0 2026-09-11\n  - earlier repair\n")
    for task in M.TASKS:
        put(root, f"task-{task}_events.json", json.dumps({"StimulusPresentation":{"SoftwareRRID":"SCR_006571"}}))
        put(root, f"task-{task}_bold.json", '{"ImageType":["ORIGINAL"]}')
    for sub in M.SUBJECTS:
        scans = "filename\tacq_time\n"
        for run in range(1, 6):
            stem = f"sub-{sub}/func/sub-{sub}_task-trust_run-{run:02d}"
            put(root, stem + "_bold.nii.gz", b"test-image")
            put(root, stem + "_bold.json", '{"ImageType":["ORIGINAL"]}')
            rows = "onset\tduration\ttrial_type\n"
            if run != 5:
                rows += "1\t2\tchoice_friend\n"
            put(root, stem + "_events.tsv", rows)
            scans += f"func/sub-{sub}_task-trust_run-{run:02d}_bold.nii.gz\t1919-01-01T12:00:00\n"
        put(root, f"sub-{sub}/sub-{sub}_scans.tsv", scans)
        intended = [f"func/sub-{sub}_task-trust_run-04_bold.nii.gz", f"func/sub-{sub}_task-trust_run-05_bold.nii.gz"]
        put(root, f"sub-{sub}/fmap/sub-{sub}_phasediff.json", json.dumps({"IntendedFor":intended}))
        for run in (4, 5, 50):
            put(root, f"derivatives/fmriprep/sub-{sub}/func/sub-{sub}_task-trust_run-{run}_bold.nii.gz", b"derivative")
        put(root, f"derivatives/fmriprep/sub-{sub}/anat/sub-{sub}_T1w.nii.gz", b"anatomy")
    for task in ("ultimatum", "sharedreward"):
        stem = f"sub-134/func/sub-134_task-{task}_run-05_bold"
        put(root, stem + ".nii.gz", b"other-task")
        put(root, stem + ".json", '{"ImageType":["ORIGINAL"]}')


class Repairs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "dataset"
        fixture(self.root)
        coverage = patch.object(M, "EXPECTED_BOLD_COUNTS", {10, 11, 12})
        coverage.start()
        self.addCleanup(coverage.stop)

    def test_preview_does_not_write(self):
        before = {str(p):p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        plan = M.make_plan(self.root)
        self.assertTrue(plan)
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_apply_backup_scope_references_and_idempotence(self):
        plan = M.make_plan(self.root)
        backup = self.base / "backup"
        M.apply_plan(self.root, backup, plan)
        for c in plan:
            self.assertEqual(M.digest(backup / "originals" / c.path), c.before)
            if c.replacement is None:
                self.assertFalse((self.root / c.path).exists())
        self.assertTrue((backup / "COMPLETE").is_file())
        self.assertTrue((backup / "deletions.tsv").is_file())
        for sub in M.SUBJECTS:
            for run in (4, 50):
                self.assertTrue((self.root / f"derivatives/fmriprep/sub-{sub}/func/sub-{sub}_task-trust_run-{run}_bold.nii.gz").is_file())
            self.assertNotIn("run-05", (self.root / f"sub-{sub}/sub-{sub}_scans.tsv").read_text())
            self.assertNotIn("run-05", (self.root / f"sub-{sub}/fmap/sub-{sub}_phasediff.json").read_text())
        self.assertTrue((self.root / "sub-134/func/sub-134_task-ultimatum_run-05_bold.nii.gz").exists())
        self.assertEqual(M.make_plan(self.root), [])

    def test_nonempty_excluded_events_block_all_changes(self):
        p = self.root / "sub-134/func/sub-134_task-trust_run-05_events.tsv"
        p.write_text("onset\tduration\ttrial_type\n1\t2\tchoice_friend\n")
        with self.assertRaisesRegex(ValueError, "non-placeholder"):
            M.make_plan(self.root)

    def test_sparse_or_git_tree_rejected(self):
        (self.root / ".git").mkdir()
        with self.assertRaisesRegex(ValueError, "Git/annex"):
            M.make_plan(self.root)
        (self.root / ".git").rmdir()
        (self.root / "sub-134/func/sub-134_task-trust_run-01_bold.nii.gz").unlink()
        with self.assertRaises(ValueError):
            M.make_plan(self.root)

    def test_missing_per_image_value_blocks_inheritance_change(self):
        (self.root / "sub-134/func/sub-134_task-trust_run-01_bold.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "ImageType"):
            M.make_plan(self.root)

    def test_symlink_rejected(self):
        p = self.root / "sub-134/func/sub-134_task-trust_run-05_bold.nii.gz"
        p.unlink()
        other = put(self.base, "external.nii.gz", b"external")
        p.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "annex link"):
            M.make_plan(self.root)

    def test_existing_backup_or_changed_source_rejected(self):
        plan = M.make_plan(self.root)
        backup = self.base / "backup"
        backup.mkdir()
        with self.assertRaises(FileExistsError):
            M.apply_plan(self.root, backup, plan)
        (self.root / plan[0].path).write_text("unexpected change")
        with self.assertRaisesRegex(ValueError, "source changed"):
            M.apply_plan(self.root, self.base / "new-backup", plan)

    def test_hardlinked_staging_metadata_not_modified(self):
        staged = self.base / "staged-description.json"
        original = self.root / "dataset_description.json"
        os.link(original, staged)
        before = staged.read_bytes()
        M.apply_plan(self.root, self.base / "backup", M.make_plan(self.root))
        self.assertEqual(staged.read_bytes(), before)
        self.assertEqual(json.loads(original.read_text())["DatasetType"], "raw")

    def test_backup_inside_dataset_rejected(self):
        with self.assertRaisesRegex(ValueError, "backup must be outside"):
            M.apply_plan(self.root, self.root / "backup", M.make_plan(self.root))

    def test_coverage_guard_rejects_partial_dataset(self):
        with patch.object(M, "EXPECTED_BOLD_COUNTS", {418, 419, 420}):
            with self.assertRaisesRegex(ValueError, "BOLD coverage"):
                M.make_plan(self.root)

    def test_repository_keeps_per_image_imagetype(self):
        for task in M.TASKS:
            parent = json.loads((ROOT / f"bids/task-{task}_bold.json").read_text())
            self.assertNotIn("ImageType", parent)
            children = list((ROOT / "bids").glob(f"sub-*/func/*_task-{task}_*_bold.json"))
            self.assertTrue(children)
            for child in children:
                self.assertTrue(json.loads(child.read_text())["ImageType"])

    def test_old_download_receives_complete_release_overlay(self):
        # A full download can still lack additions uploaded from a sparse tree.
        sys.path.insert(0, str(ROOT / "code"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "code")))
        import prepare_openneuro_2_2_release as release
        for run in range(1, 219):
            put(self.root, f"derivatives/single_trials/sub-104/sub-104_task-trust_run-{run:02d}_singletrial-Act.nii.gz", b"unchanged-trial-image")
        for relative in release.SUB144_SINGLE_TRIALS:
            put(self.root, relative, b"unchanged-trial-image")
        for task in M.TASKS:
            (self.root / f"task-{task}_events.json").unlink()
        plan = M.make_plan(self.root, ROOT)
        by_path = {c.path:c for c in plan}
        self.assertEqual(by_path["task-trust_events.json"].before, "")
        self.assertIn(b"RRID:SCR_006571", by_path["task-trust_events.json"].replacement)
        ratings = [c for c in plan if c.path.endswith("_beh.tsv")]
        self.assertEqual(len(ratings), 220)
        self.assertFalse(any("single_trials/" in c.path for c in plan))
        backup = self.base / "backup"
        M.apply_plan(self.root, backup, plan)
        self.assertEqual(M.make_plan(self.root, ROOT), [])
        manifest = json.loads((backup / "repair-manifest.json").read_text())
        self.assertTrue(any(c["action"] == "create" for c in manifest["files"]))

    def test_validator_uses_full_tree_and_pinned_profile(self):
        sys.path.insert(0, str(ROOT / "code"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "code")))
        import validate_openneuro_full_dataset as validation
        args = validation.command(self.root.resolve(), (self.base / "report").resolve(), "/bin/deno")
        self.assertIn("jsr:@bids/validator@3.0.1", args)
        self.assertEqual(args[-1], str(self.root.resolve()))
        self.assertNotIn("--git-ref", args)
        self.assertNotIn("--ignoreWarnings", args)
        self.assertIn("schema-1.2.7-datacite.json", args[args.index("--schema") + 1])


if __name__ == "__main__":
    unittest.main()
