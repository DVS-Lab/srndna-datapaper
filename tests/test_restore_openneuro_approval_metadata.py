import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import restore_openneuro_approval_metadata as repair


class ApprovalMetadataTests(unittest.TestCase):
    def setUp(self):
        self.restored = json.loads((ROOT / "bids/dataset_description.json").read_text())
        self.old = json.loads(repair.git(ROOT, "show", "4bfc9aa:bids/dataset_description.json"))

    def test_only_three_repository_fields_changed(self):
        delta = {k for k in self.old.keys() | self.restored.keys() if self.old.get(k) != self.restored.get(k)}
        self.assertEqual(delta, set(repair.FIELDS))
        self.assertEqual(self.restored["EthicsApprovals"], ["Temple IRB #24452"])
        self.assertIn("Tania Giovannetti", self.restored["Acknowledgements"])
        self.assertIn("Nicole Henninger", self.restored["Acknowledgements"])
        self.assertEqual(self.restored["Authors"], ["David V. Smith", "Rita M. Ludwig", "Jeffrey B. Dennison", "Crystal Reeck", "Dominic S. Fareri"])

    def test_preserve_other_metadata_and_reject_independent_target_edits(self):
        current = dict(self.old, NewField="retain", HowToAcknowledge="independent new citation")
        result = repair.correction(current, self.restored, self.old)
        self.assertEqual(result["NewField"], "retain")
        self.assertEqual(result["HowToAcknowledge"], "independent new citation")
        current["EthicsApprovals"] = ["Different protocol"]
        with self.assertRaisesRegex(ValueError, "independently edited"):
            repair.correction(current, self.restored, self.old)

    def test_preview_upload_resume_and_no_image_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, remote, dataset, report = [root / n for n in ("candidate", "remote.git", "download", "report")]
            repair.git(root, "init", repo)
            repair.git(repo, "config", "user.name", "Metadata test")
            repair.git(repo, "config", "user.email", "test@example.invalid")
            (repo / repair.FILE).write_text(repair.encode(dict(self.old, RemoteOnly="preserve")))
            (repo / "image.nii.gz").write_bytes(b"untouched imaging sentinel")
            repair.git(repo, "add", repair.FILE, "image.nii.gz")
            repair.git(repo, "commit", "-m", "original")
            base = repair.git(repo, "rev-parse", "HEAD")
            repair.git(root, "init", "--bare", remote)
            repair.git(repo, "remote", "add", "origin", remote)
            repair.git(repo, "push", "origin", "HEAD:refs/heads/main")
            dataset.mkdir()
            (dataset / repair.FILE).write_text(repair.encode(dict(self.old, LocalOnly="preserve")))
            args = argparse.Namespace(candidate=repo, dataset_root=dataset, report_dir=report, execute=False)
            with patch.object(repair, "URL", str(remote)):
                repair.run(args)
                self.assertEqual(repair.head(repo), base)
                self.assertNotIn("EthicsApprovals", json.loads((dataset / repair.FILE).read_text()))
                args.execute = True
                repair.run(args)
                commit = repair.head(repo)
                self.assertEqual(repair.git(repo, "diff", "--name-only", base, commit), repair.FILE)
                self.assertEqual(repair.git(repo, "rev-parse", "HEAD"), base)
                self.assertEqual(repair.git(repo, "status", "--porcelain"), "")
                published = json.loads(repair.git(repo, "show", f"{commit}:{repair.FILE}"))
                self.assertEqual(published["RemoteOnly"], "preserve")
                downloaded = json.loads((dataset / repair.FILE).read_text())
                self.assertEqual(downloaded["LocalOnly"], "preserve")
                self.assertEqual(downloaded["EthicsApprovals"], ["Temple IRB #24452"])
                receipt = json.loads((report / "approval-repair.json").read_text())
                self.assertEqual(receipt["image_files_transferred"], 0)
                self.assertTrue(receipt["remote_main_verified"])
                repair.run(args)
                self.assertEqual(repair.head(repo), commit)


if __name__ == "__main__":
    unittest.main()
