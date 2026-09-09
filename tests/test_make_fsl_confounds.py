import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "code" / "make_fsl_confounds.py"
SPEC = importlib.util.spec_from_file_location("make_fsl_confounds", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MakeFslConfoundsTests(unittest.TestCase):
    def write_source(self, root: Path) -> Path:
        func = root / "derivatives/fmriprep/sub-144/func"
        func.mkdir(parents=True)
        stem = "sub-144_task-trust_run-1"
        bold = func / f"{stem}_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
        bold.write_bytes(b"bold")
        source = func / f"{stem}_desc-confounds_timeseries.tsv"
        columns = [
            "cosine00",
            "non_steady_state_outlier00",
            *MODULE.MOTION,
            *MODULE.ACOMPCOR,
            *MODULE.FRAMEWISE_DISPLACEMENT,
            "unused",
        ]
        source.write_text(
            "\t".join(columns)
            + "\n"
            + "\t".join(["0.1", "1", *("0" for _ in MODULE.MOTION),
                          *("0.2" for _ in MODULE.ACOMPCOR), "n/a", "99"])
            + "\n"
            + "\t".join(["0.2", "0", *("1" for _ in MODULE.MOTION),
                          *("0.3" for _ in MODULE.ACOMPCOR), "0.4", "99"])
            + "\n",
            encoding="utf-8",
        )
        return source

    def test_scoped_generation_writes_numeric_headerless_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_source(root)
            output_root = root / "work/confounds"
            result = MODULE.main(
                [
                    "trust",
                    "--dataset-root",
                    str(root),
                    "--output-root",
                    str(output_root),
                    "--all-subjects",
                ]
            )
            self.assertEqual(result, 0)
            output = (
                output_root
                / "sub-144/sub-144_task-trust_run-1_desc-fslConfounds.tsv"
            )
            rows = [line.split("\t") for line in output.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(rows[0]), 15)
            self.assertEqual(rows[0][-1], "0")
            self.assertNotIn("99", rows[0])

    def test_missing_required_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "confounds.tsv"
            source.write_text("trans_x\n0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required confound columns"):
                MODULE.convert(source, root / "output.tsv")


if __name__ == "__main__":
    unittest.main()
