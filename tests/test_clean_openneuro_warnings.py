import gzip
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import clean_openneuro_warnings as M


def compressed(data=b"NIfTI header and image data" * 200, name="original.nii", mtime=12345):
    buffer = io.BytesIO()
    with gzip.GzipFile(filename=name, fileobj=buffer, mode="wb", mtime=mtime) as f:
        f.write(data)
    return buffer.getvalue()


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "dataset"
        self.image = self.root / "sub-104/func/sub-104_task-trust_run-01_bold.nii.gz"
        self.image.parent.mkdir(parents=True)
        self.image.write_bytes(compressed())
        self.sidecar = self.image.with_name(self.image.name.removesuffix(".nii.gz") + ".json")
        self.sidecar.write_text(json.dumps(dict(PulseSequenceDetails="%SiemensSeq%_ep2d_bold", ScanningSequence="EP")))
        (self.root / "participants.tsv").write_text("participant_id\nsub-104\n")
        (self.root / ".bidsignore").write_text("derivatives\nsub-2*\n")
        (self.root / "dataset_description.json").write_text('{"DatasetType":"raw"}')
        for name, value in [("EXPECTED_RAW_IMAGES", 1), ("EXPECTED_BOLD_IMAGES", 1)]:
            p = patch.object(M, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(M, "check_full_dataset")
        p.start()
        self.addCleanup(p.stop)

    def test_payload_and_deflate_bytes_unchanged(self):
        target = self.base / "clean.nii.gz"
        expected = M.payload_digest(self.image)
        self.assertEqual(M.normalize(self.image, target), expected)
        self.assertEqual(M.payload_digest(target), expected)
        with self.image.open("rb") as old, target.open("rb") as new:
            original, clean = M.header(old)
            self.assertNotEqual(original, clean)
            self.assertEqual(new.read(10), clean)
            self.assertEqual(old.read(), new.read())
        with target.open("rb") as f:
            original, clean = M.header(f)
            self.assertEqual(original, clean)

    def test_comment_removed(self):
        b = bytearray(compressed(name=""))
        b[3] |= 0x10
        self.image.write_bytes(b[:10] + b"private comment\0" + b[10:])
        target = self.base / "clean.nii.gz"
        M.normalize(self.image, target)
        self.assertNotIn(b"private comment", target.read_bytes())

    def test_highly_compressible_large_payload(self):
        self.image.write_bytes(compressed(data=b"N" * (8 * 1024 * 1024)))
        target = self.base / "large-clean.nii.gz"
        self.assertEqual(M.normalize(self.image, target), M.payload_digest(self.image))

    def test_unsupported_and_truncated_headers(self):
        for value in (b"bad", b"\x1f\x8b\x08\x04" + b"\0" * 6,
                      b"\x1f\x8b\x08\x08" + b"\0" * 6 + b"unclosed"):
            with self.assertRaises(ValueError):
                M.header(io.BytesIO(value))

    def test_corruption_and_second_member_rejected(self):
        for value in (compressed()[:-3], compressed() + compressed(), compressed() + b"trailing"):
            self.image.write_bytes(value)
            with self.assertRaises((ValueError, EOFError)):
                M.normalize(self.image, self.base / "clean.nii.gz")

    def test_backup_atomic_resume_and_idempotence(self):
        before = self.image.read_bytes()
        sibling = self.base / "earlier-staging.nii.gz"
        os.link(self.image, sibling)
        items = M.plan(self.root)
        self.assertEqual(len(items), 2)
        backup = self.base / "backup"
        M.apply(self.root, backup, items)
        self.assertEqual(sibling.read_bytes(), before)
        self.assertEqual((backup / "originals" / self.image.relative_to(self.root)).read_bytes(), before)
        self.assertTrue((backup / "COMPLETE").exists())
        self.assertEqual(json.loads(self.sidecar.read_text())["PulseSequenceType"], "Echo-planar imaging")
        self.assertEqual(M.plan(self.root), [])
        after = self.image.read_bytes()
        M.apply(self.root, backup, [], resume=True)
        self.assertEqual(self.image.read_bytes(), after)
        self.assertTrue(json.loads((backup / "cleanup-manifest.json").read_text())["files"][0]["uncompressed_sha256"])

    def test_bad_sequence_and_symlink_rejected(self):
        self.sidecar.write_text('{"PulseSequenceDetails":"unknown"}')
        with self.assertRaisesRegex(ValueError, "unrecognized sequence"):
            M.plan(self.root)
        original = self.base / "original.gz"
        self.image.rename(original)
        self.image.symlink_to(original)
        with self.assertRaisesRegex(ValueError, "regular"):
            M.plan(self.root)

    def test_unsafe_backup_and_changed_source_rejected(self):
        items = M.plan(self.root)
        with self.assertRaises(ValueError):
            M.apply(self.root, self.root / "backup", items)
        self.sidecar.write_text("{}")
        with self.assertRaisesRegex(ValueError, "source changed"):
            M.apply(self.root, self.base / "backup", items)
        with self.image.open("rb") as f:
            original, clean = M.header(f)
        self.assertNotEqual(original, clean)

    def test_resume_detects_already_renamed_output(self):
        items = M.plan(self.root)
        backup = self.base / "backup"
        original_write = M.atomic_write
        calls = 0
        def interrupt(path, content):
            nonlocal calls
            if path.name == "cleanup-manifest.json":
                calls += 1
                if calls == 3:
                    raise OSError("simulated disconnect after first replacement")
            original_write(path, content)
        with patch.object(M, "atomic_write", side_effect=interrupt):
            with self.assertRaises(OSError):
                M.apply(self.root, backup, items)
        M.apply(self.root, backup, [], resume=True)
        self.assertEqual(M.plan(self.root), [])

    def test_participant_audit_does_not_change_records(self):
        (self.root / "sub-204").mkdir()
        result = M.participant_audit(self.root)
        self.assertEqual(result["directories_without_participant"], ["sub-204"])
        self.assertEqual(result["participants_without_directory"], [])


if __name__ == "__main__":
    unittest.main()
