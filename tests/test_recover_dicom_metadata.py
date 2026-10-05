import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import recover_dicom_metadata as M


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root, self.work = self.base / "dataset", self.base / "private"
        self.image = self.root / "sub-143/fmap/sub-143_magnitude1.nii.gz"
        self.sidecar = self.image.with_name("sub-143_magnitude1.json")
        self.folder = self.work / "sub-143/attempt-test"
        self.folder.mkdir(parents=True)
        self.source = self.folder / "series-7_echo-1.json"
        self.fresh_image = self.source.with_suffix(".nii.gz")
        self.old = dict(SeriesNumber=7, ProtocolName="fmap", EchoTime=.00492, RepetitionTime=.645,
                        MRAcquisitionType="2D", ScanningSequence="GR", ImageType=["ORIGINAL", "PRIMARY", "M", "ND"],
                        ImageOrientationPatientDICOM=[1,0,0,0,1,0], SliceThickness=3., Manufacturer="Siemens")
        self.new = dict(self.old, CoilCombinationMethod="Sum of Squares", MatrixCoilMode="SENSE",
                        NonlinearGradientCorrection=False, SliceTiming=[0., .1, .2, .3],
                        PatientName="DO_NOT_EXPORT", AcquisitionDateTime="DO_NOT_EXPORT")
        self.save_image(self.image)
        self.save_image(self.fresh_image)
        self.sidecar.write_bytes(M.json_bytes(self.old))
        M.private_write(self.work / "extraction-config.json", dict(dataset_root=str(self.root), converter=M.CONVERTER_VERSION))
        self.save_source()
        p = patch.object(M, "raw_images", return_value=[self.image])
        p.start(); self.addCleanup(p.stop)

    def save_image(self, path, affine=None, shape=(2,3,4), axis=2):
        path.parent.mkdir(parents=True, exist_ok=True)
        img = nib.Nifti1Image(np.zeros(shape, dtype=np.int16), np.eye(4) if affine is None else affine)
        img.header.set_dim_info(slice=axis)
        nib.save(img, path)

    def save_source(self):
        self.source.write_bytes(M.json_bytes(self.new))
        M.private_write(self.work / "sub-143/complete.json", dict(attempt=self.folder.name,
                        json_sha256={p.name: M.digest(p) for p in self.folder.glob("*.json")}))

    def plan(self, suffix="one"):
        report = self.base / ("report-" + suffix)
        public = self.base / ("public-" + suffix)
        result = M.make_plan(self.root, self.work, report, public)
        return result, report / "patch.json", public

    def test_preview_missing_only_privacy_and_apply(self):
        original = self.sidecar.read_bytes()
        image_hash = M.digest(self.image)
        earlier_stage = self.base / "hardlinked.json"
        os.link(self.sidecar, earlier_stage)
        summary, plan, public = self.plan()
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["proposed_fields"]["SliceTiming"], 1)
        self.assertEqual(self.sidecar.read_bytes(), original)
        backup = self.base / "backup"
        M.apply(self.root, plan, backup)
        data = json.loads(self.sidecar.read_text())
        self.assertEqual(data["SliceTiming"], self.new["SliceTiming"])
        self.assertNotIn("PatientName", data)
        self.assertNotIn("AcquisitionDateTime", data)
        for path in public.iterdir():
            self.assertNotIn("DO_NOT_EXPORT", path.read_text())
            self.assertNotIn(str(self.work), path.read_text())
        self.assertEqual(earlier_stage.read_bytes(), original)
        self.assertEqual(M.digest(self.image), image_hash)
        after = self.sidecar.read_bytes()
        M.apply(self.root, plan, backup)
        self.assertEqual(self.sidecar.read_bytes(), after)
        summary, _, _ = self.plan("after")
        self.assertEqual(summary["proposed_sidecars"], 0)

    def test_identity_requires_echo_protocol_type_and_orientation(self):
        self.assertTrue(M.matches(self.old, self.new))
        for key, value in [("SeriesNumber", 6), ("EchoTime", .00738), ("ProtocolName", "another"),
                           ("ImageType", ["ORIGINAL", "PRIMARY", "P", "ND"]),
                           ("ImageOrientationPatientDICOM", [0,1,0,1,0,0])]:
            altered = dict(self.new, **{key: value})
            self.assertFalse(M.matches(self.old, altered), key)
        for key in M.REQUIRED_MATCH:
            altered = dict(self.new); del altered[key]
            self.assertFalse(M.matches(self.old, altered), key)
        self.assertTrue(M.matches(self.old, dict(self.new, ImageType=self.old["ImageType"] + ["MAGNITUDE"])))

    def test_scanning_sequence_representation_only(self):
        old = dict(self.old, ScanningSequence="GR_IR")
        new = dict(self.new, ScanningSequence="GR\\IR")
        self.assertTrue(M.matches(old, new))
        self.assertTrue(M.matches(new, old))
        for value in ("GR", "IR", "SE", "EP", "IR_GR", "GR/IR", "GR_IR_OTHER"):
            self.assertFalse(M.matches(old, dict(new, ScanningSequence=value)))
        self.assertFalse(M.matches(old, dict(new, ProtocolName="different")))
        self.assertFalse(M.matching_equal("ProtocolName", "GR_IR", "GR\\IR"))
        self.old, self.new = old, new
        self.sidecar.write_bytes(M.json_bytes(old)); self.save_source()
        summary, plan, public = self.plan()
        self.assertEqual(summary["matched"], 1)
        self.assertIn("ScanningSequence:GR_IR=GR\\IR", (public / "matching.tsv").read_text())
        M.apply(self.root, plan, self.base / "backup")
        self.assertEqual(json.loads(self.sidecar.read_text())["ScanningSequence"], "GR_IR")

    def test_require_complete_stops_after_saving_unmatched_audit(self):
        self.new["ScanningSequence"] = "EP"; self.save_source()
        argv = ["recover", "plan", "--dataset-root", str(self.root),
                "--work-root", str(self.work), "--report-root", str(self.base / "report"),
                "--public-report", str(self.base / "public"), "--require-complete"]
        previous = os.umask(0o077)
        try:
            with patch.object(sys, "argv", argv):
                self.assertEqual(M.main(), 2)
        finally:
            os.umask(previous)
        self.assertTrue((self.base / "public/summary.json").is_file())
        self.assertEqual(json.loads(self.sidecar.read_text()), self.old)

    def test_duplicate_and_unmatched_are_held(self):
        twin = self.folder / "series-7_echo-1a.json"
        twin.write_bytes(self.source.read_bytes()); self.save_source()
        summary, plan, _ = self.plan()
        self.assertEqual(summary["ambiguous"], 1)
        self.assertFalse(json.loads(plan.read_text())["files"])
        self.new["SeriesNumber"] = 999
        twin.unlink(); self.save_source()
        summary, _, _ = self.plan("unmatched")
        self.assertEqual(summary["unmatched"], 1)

    def test_no_cross_subject_matching(self):
        # Candidate lookup is participant-specific even for identical series.
        self.assertEqual(M.candidates(self.work, "sub-144"), [])

    def test_inheritance_preserved_and_fingerprint_guarded(self):
        broad = self.root / "magnitude1.json"
        broad.write_bytes(M.json_bytes({"MatrixCoilMode": "SENSE"}))
        summary, plan, _ = self.plan()
        self.assertEqual(summary["proposed_fields"]["MatrixCoilMode"], 0)
        broad.write_bytes(M.json_bytes({"MatrixCoilMode": "GRAPPA"}))
        with self.assertRaisesRegex(ValueError, "inherited sidecars changed"):
            M.apply(self.root, plan, self.base / "backup")

    def test_geometry_flip_or_shape_change_blocks_timing(self):
        for affine, shape in [(np.diag([1,1,-1,1]), (2,3,4)), (np.eye(4), (2,3,5))]:
            self.save_image(self.fresh_image, affine=affine, shape=shape)
            additions, status, _ = M.timing_additions(self.old, self.new, self.image, self.fresh_image)
            self.assertEqual(status, "geometry_mismatch")
            self.assertFalse(additions)
        summary, _, _ = self.plan()
        self.assertEqual(summary["conflict"], 1)
        self.assertEqual(summary["proposed_sidecars"], 0)

    def test_timing_axis_limits_and_nan(self):
        for timing in [[0,.1], [0,.1,.2,float("nan")], [0,.1,.2,.645], [0,.1,.2,-.1]]:
            _, status, _ = M.timing_additions(self.old, dict(self.new, SliceTiming=timing), self.image, self.fresh_image)
            self.assertEqual(status, "invalid_timing")
        self.save_image(self.image, axis=None)
        self.save_image(self.fresh_image, axis=None)
        _, status, _ = M.timing_additions(self.old, self.new, self.image, self.fresh_image)
        self.assertEqual(status, "source_slice_axis_missing")

    def test_explicit_direction_and_existing_negative_axis(self):
        new = dict(self.new, SliceEncodingDirection="k-")
        additions, status, _ = M.timing_additions(self.old, new, self.image, self.fresh_image)
        self.assertEqual(status, "geometry_verified")
        self.assertEqual(additions["SliceEncodingDirection"], "k-")
        _, status, _ = M.timing_additions(dict(self.old, SliceEncodingDirection="k-"), self.new, self.image, self.fresh_image)
        self.assertEqual(status, "slice_axis_conflict")

    def test_json_only_can_patch_coil_but_not_timing(self):
        self.fresh_image.unlink()
        summary, _, public = self.plan()
        self.assertEqual(summary["proposed_fields"]["CoilCombinationMethod"], 1)
        self.assertEqual(summary["proposed_fields"]["SliceTiming"], 0)
        self.assertIn("scratch_image_required", (public / "matching.tsv").read_text())

    def test_existing_conflict_holds_entire_file(self):
        self.old["CoilCombinationMethod"] = "Adaptive Combine"
        self.sidecar.write_bytes(M.json_bytes(self.old))
        summary, _, _ = self.plan()
        self.assertEqual(summary["conflict"], 1)
        self.assertEqual(summary["proposed_sidecars"], 0)

    def test_gradient_flag_requires_evidence(self):
        self.assertTrue(M.approved_value("NonlinearGradientCorrection", False, self.new))
        self.assertFalse(M.approved_value("NonlinearGradientCorrection", True, self.new))
        self.assertFalse(M.approved_value("NonlinearGradientCorrection", "false", self.new))
        self.assertFalse(M.approved_value("NonlinearGradientCorrection", False, dict(self.new, ImageType=["M"])))

    def test_changed_source_and_target_refused(self):
        _, plan, _ = self.plan()
        self.source.write_text("{}")
        with self.assertRaisesRegex(ValueError, "source changed"):
            M.apply(self.root, plan, self.base / "backup")
        self.save_source()
        self.sidecar.write_text("{}")
        with self.assertRaisesRegex(ValueError, "sidecar changed"):
            M.apply(self.root, plan, self.base / "backup2")

    def test_manifest_cannot_add_private_fields_or_overwrite(self):
        _, path, _ = self.plan()
        original = json.loads(path.read_text())
        for key, value, message in [("PatientName", "private", "unapproved"), ("CoilCombinationMethod", "bogus", "source-backed")]:
            plan = copy.deepcopy(original)
            plan["files"][0]["additions"][key] = value
            path.write_bytes(M.json_bytes(plan))
            with self.assertRaisesRegex(ValueError, message):
                M.apply(self.root, path, self.base / ("backup-" + key))

    def test_interruption_resume_and_backup_checksum(self):
        _, path, _ = self.plan()
        backup = self.base / "backup"
        real = M.atomic_write
        def interrupt(destination, content):
            if destination == self.sidecar:
                raise OSError("simulated interruption")
            return real(destination, content)
        with patch.object(M, "atomic_write", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "simulated"):
                M.apply(self.root, path, backup)
        M.apply(self.root, path, backup)
        saved = backup / "originals" / self.sidecar.relative_to(self.root)
        saved.write_text("corrupt")
        with self.assertRaisesRegex(ValueError, "backup checksum"):
            M.apply(self.root, path, backup)

    def test_unsafe_backup_and_symlink(self):
        _, path, _ = self.plan()
        with self.assertRaisesRegex(ValueError, "disjoint"):
            M.apply(self.root, path, self.root / "backup")
        target = self.base / "other.json"
        self.sidecar.rename(target)
        self.sidecar.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "regular"):
            M.apply(self.root, path, self.base / "backup")

    def test_extract_command_resumes_and_rejects_changed_output(self):
        dicoms = self.base / "dicoms"
        (dicoms / "SMITH-AgingDM-143").mkdir(parents=True)
        work = self.base / "extract"
        calls = []
        def fake_run(command, **kwargs):
            if command[-1] == "--version":
                return SimpleNamespace(stdout=M.CONVERTER_VERSION, stderr="", returncode=0)
            calls.append(command)
            output = Path(command[command.index("-o")+1])
            (output / "series-7_echo-1.json").write_bytes(M.json_bytes(self.new))
            self.save_image(output / "series-7_echo-1.nii.gz")
            return SimpleNamespace(returncode=0)
        with patch.object(M.shutil, "which", return_value="/usr/bin/dcm2niix"), patch.object(M.subprocess, "run", side_effect=fake_run):
            M.extract(self.root, dicoms, work, with_images=True)
            M.extract(self.root, dicoms, work, with_images=True)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1:7], ["-g", "i", "-b", "y", "-ba", "y"])
            self.assertIn("-z", calls[0])
            self.assertEqual(work.stat().st_mode & 0o777, 0o700)
            source = next(work.glob("sub-143/attempt-*/series-*.json"))
            source.write_text("{}")
            with self.assertRaisesRegex(ValueError, "completed extraction changed"):
                M.extract(self.root, dicoms, work, with_images=True)

    def test_extract_failure_retains_attempt_and_retries(self):
        dicoms = self.base / "dicoms"
        (dicoms / "SMITH-AgingDM-143").mkdir(parents=True)
        work = self.base / "extract"
        attempts = []
        def fake_run(command, **kwargs):
            if command[-1] == "--version":
                return SimpleNamespace(stdout=M.CONVERTER_VERSION, stderr="", returncode=0)
            output = Path(command[command.index("-o")+1]); attempts.append(output)
            if len(attempts) == 1:
                return SimpleNamespace(returncode=1)
            (output / "series-7_echo-1.json").write_bytes(M.json_bytes(self.new))
            return SimpleNamespace(returncode=0)
        with patch.object(M.shutil, "which", return_value="/usr/bin/dcm2niix"), patch.object(M.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "extraction failed"):
                M.extract(self.root, dicoms, work)
            M.extract(self.root, dicoms, work)
        self.assertEqual(len(attempts), 2)
        self.assertNotEqual(*attempts)
        self.assertTrue(attempts[0].is_dir())


if __name__ == "__main__":
    unittest.main()
