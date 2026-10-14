import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import finalize_openneuro_release as release


class MetadataTests(unittest.TestCase):
    def test_current_report_is_accepted_without_suppressing_warnings(self):
        report = json.loads((ROOT / "results/openneuro_validation/primary50-metadata-v1/validation.json").read_text())
        result = release.validation_summary(report, {})
        self.assertEqual(result["warning_instances"], 1529)
        self.assertEqual(result["errors"], 0)
        report["issues"]["issues"].append(dict(severity="warning", code="NEW_WARNING"))
        with self.assertRaisesRegex(ValueError, "new validation"):
            release.validation_summary(report, {})

    def test_real_participant_mismatch_and_errors_stop_release(self):
        report = json.loads((ROOT / "results/openneuro_validation/primary50-metadata-v1/validation.json").read_text())
        bad = copy.deepcopy(report)
        bad["summary"]["subjects"].append("204")
        with self.assertRaisesRegex(ValueError, "inventory"):
            release.validation_summary(bad, {})
        report["issues"]["issues"].append(dict(severity="error", code="ERROR"))
        with self.assertRaisesRegex(ValueError, "has errors"):
            release.validation_summary(report, {})

    def test_safe_paths(self):
        for value in ("/tmp/escape", "../escape", ".git/config", "x\ny"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.safe_relative(value)


@unittest.skipUnless(shutil.which("git-annex"), "requires native git-annex")
class NativeGitAnnexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "release"
        self.repo = self.work / "candidate"
        self.report = self.root / "report"
        self.work.mkdir()
        release.git(self.work, "init", str(self.repo))
        release.git(self.repo, "config", "user.name", "Release test")
        release.git(self.repo, "config", "user.email", "test@example.invalid")
        release.git(self.repo, "config", "core.symlinks", "true")
        (self.repo / "README").write_text("original\n")
        (self.repo / "excluded.tsv").write_text("old\n")
        (self.repo / "keep.tsv").write_text("untouched\n")
        release.git(self.repo, "add", "README", "excluded.tsv", "keep.tsv")
        release.git(self.repo, "commit", "-m", "base")
        release.git(self.repo, "checkout", "-b", release.BRANCH)
        self.base = release.git(self.repo, "rev-parse", "HEAD")
        release.git(self.repo, "annex", "init", "test")
        release.git(self.repo, "config", "annex.addunlocked", "false")
        # Match the real dataset: old script was annexed, new text must not be.
        (self.repo / "script.sh").write_text("#!/bin/sh\necho old\n")
        release.git(self.repo, "annex", "add", "script.sh")
        release.git(self.repo, "commit", "-m", "historical script in annex")
        self.base = release.git(self.repo, "rev-parse", "HEAD")
        self.source = self.root / "source"
        self.source.mkdir()
        rows = []
        for rel, data in (("README", b"updated\n"), ("script.sh", b"#!/bin/sh\necho new\n"),
                          ("sub-104/func/image.nii.gz", b"test image bytes\n")):
            path = self.source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            annex = rel.endswith(".nii.gz")
            rows.append(dict(path=rel, source=str(path), sha256=release.sha256(path),
                             bytes=len(data), mode="120000" if annex else "100644", annex=annex))
        self.plan = dict(files=rows, deletions=[dict(path="excluded.tsv")])
        release.save(self.work / "plan.json", self.plan)
        release.save(self.work / "prepared.json", dict(plan_sha256=release.sha256(self.work / "plan.json")))
        release.save(self.work / "candidate.json", dict(base=self.base))

    def test_build_native_annex_modes_unchanged_paths_and_resume(self):
        release.build(self.work, self.report)
        state = json.loads((self.work / "candidate.json").read_text())
        tree = release.tree_entries(self.repo, "HEAD")
        self.assertEqual(tree["script.sh"][0], "100644")
        self.assertEqual(tree["sub-104/func/image.nii.gz"][0], "120000")
        self.assertFalse((self.repo / "script.sh").is_symlink())
        self.assertTrue((self.repo / "sub-104/func/image.nii.gz").is_symlink())
        self.assertEqual((self.repo / "keep.tsv").read_text(), "untouched\n")
        self.assertNotIn("excluded.tsv", tree)
        self.assertEqual(release.git(self.repo, "rev-parse", "HEAD^"), self.base)
        release.build(self.work, self.report)
        self.assertEqual(release.git(self.repo, "rev-parse", "HEAD"), state["commit"])

    def test_reject_literal_script_stored_as_symlink(self):
        release.build(self.work, self.report)
        oid = release.git(self.repo, "rev-parse", "HEAD:script.sh")
        release.git(self.repo, "update-index", "--cacheinfo", f"120000,{oid},script.sh")
        with self.assertRaisesRegex(ValueError, "wrong Git mode"):
            release.audit_tree(self.repo, self.base, release.git(self.repo, "write-tree"), self.plan)

    def test_reject_unplanned_tree_change(self):
        release.build(self.work, self.report)
        (self.repo / "keep.tsv").write_text("unplanned\n")
        release.git(self.repo, "add", "keep.tsv")
        with self.assertRaisesRegex(ValueError, "unexpected candidate"):
            release.audit_tree(self.repo, self.base, release.git(self.repo, "write-tree"), self.plan)

    def test_source_change_refused(self):
        row = self.plan["files"][0]
        Path(row["source"]).write_text("changed after preparation\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            release.install_file(self.repo, row)

    def test_partial_install_can_resume(self):
        release.install_file(self.repo, self.plan["files"][-1])
        release.build(self.work, self.report)
        self.assertEqual(release.git(self.repo, "status", "--porcelain"), "")

    def test_upload_and_resume_using_local_git_and_annex_remotes(self):
        remote = self.root / "origin.git"
        release.git(self.root, "init", "--bare", remote)
        release.git(self.repo, "remote", "add", "origin", remote)
        release.git(self.repo, "push", "origin", "HEAD:refs/heads/main", "git-annex:git-annex")
        objects = self.root / "remote-objects"
        objects.mkdir()
        release.git(self.repo, "annex", "initremote", "openneuro", "type=directory",
                    f"directory={objects}", "encryption=none")
        with patch.object(release, "URL", str(remote)), patch.object(release.time, "sleep"):
            release.upload(self.work, self.report)
            receipt = json.loads((self.report / "upload.json").read_text())
            self.assertEqual(receipt["verified_annex_files"], 1)
            self.assertTrue(receipt["remote_main_verified"])
            self.assertFalse(receipt["snapshot_published"])
            self.assertEqual(release.remote_head(self.repo), receipt["commit"])
            release.upload(self.work, self.report)
            self.assertEqual(release.remote_head(self.repo), receipt["commit"])

    def test_remote_divergence_stops_before_transfer(self):
        release.build(self.work, self.report)
        release.git(self.repo, "remote", "add", "origin", release.URL)
        with patch.object(release, "remote_head", return_value="unrelated-new-commit"):
            with self.assertRaisesRegex(ValueError, "remote main changed"):
                release.upload(self.work, self.report)


if __name__ == "__main__":
    unittest.main()
