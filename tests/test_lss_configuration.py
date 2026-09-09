import importlib.util
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "code" / "makeSingleTrials.py"
SPEC = importlib.util.spec_from_file_location("make_lss_evs", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LssConfigurationTests(unittest.TestCase):
    def test_all_task_templates_disable_additional_smoothing(self):
        for task in ("ultimatum", "sharedreward", "trust"):
            template = (
                REPO_ROOT / "templates" / f"L1LSS_task-{task}_model-01_type-act.fsf"
            )
            match = re.search(
                r"^set fmri\(smooth\) ([0-9.]+)$",
                template.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
            self.assertIsNotNone(match, template)
            self.assertEqual(float(match.group(1)), 0.0, template)

    def test_trust_template_uses_fmriprep_preprocessing_and_cosine_filtering(self):
        template = (
            REPO_ROOT / "templates" / "L1LSS_task-trust_model-01_type-act.fsf"
        )
        contents = template.read_text(encoding="utf-8")

        expected_settings = {
            "mc": "0",
            "smooth": "0.0",
            "temphp_yn": "0",
            "motionevs": "0",
            "confoundevs": "1",
            "tempfilt_yn1": "0",
            "tempfilt_yn2": "0",
            "tempfilt_yn3": "0",
        }
        for setting, expected in expected_settings.items():
            match = re.search(
                rf"^set fmri\({re.escape(setting)}\) (\S+)$",
                contents,
                flags=re.MULTILINE,
            )
            self.assertIsNotNone(match, f"Missing fmri({setting}) in {template}")
            self.assertEqual(match.group(1), expected, f"fmri({setting}) in {template}")

    def test_trust_ev_generation_uses_observed_outcome_count(self):
        event_file = (
            REPO_ROOT
            / "bids"
            / "sub-104"
            / "func"
            / "sub-104_task-trust_run-01_events.tsv"
        )
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            output_dir = (
                output_root / "sub-104" / "SingleTrialEVs" / "task-trust" / "run01"
            )
            output_dir.mkdir(parents=True)
            stale = output_dir / "trialmodel-99_estimage-single.tsv"
            stale.write_text("stale\n", encoding="utf-8")

            trial_count = MODULE.make_run_evs(
                "trust", event_file, output_root, clean=True
            )

            self.assertEqual(trial_count, 34)
            self.assertFalse(stale.exists())
            single = output_dir / "trialmodel-1_estimage-single.tsv"
            other = output_dir / "trialmodel-1_estimage-other.tsv"
            self.assertEqual(len(single.read_text().splitlines()), 1)
            self.assertEqual(len(other.read_text().splitlines()), 33)

    def test_nontrust_ev_generation_matches_observed_trial_counts(self):
        cases = (
            ("ultimatum", "144", "01", 72),
            ("ultimatum", "144", "02", 72),
            ("sharedreward", "130", "01", 72),
        )
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory)
            for task, subject, run, expected in cases:
                event_file = (
                    REPO_ROOT
                    / "bids"
                    / f"sub-{subject}"
                    / "func"
                    / f"sub-{subject}_task-{task}_run-{run}_events.tsv"
                )
                trial_count = MODULE.make_run_evs(
                    task, event_file, output_root, clean=True
                )
                self.assertEqual(trial_count, expected, event_file)

    def test_clean_removes_stale_evs_for_a_run_with_no_estimable_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_file = root / "sub-999_task-trust_run-01_events.tsv"
            event_file.write_text("onset\tduration\ttrial_type\n", encoding="utf-8")
            output_root = root / "EVfiles"
            output_dir = (
                output_root
                / "sub-999/SingleTrialEVs/task-trust/run01"
            )
            output_dir.mkdir(parents=True)
            stale = output_dir / "trialmodel-1_estimage-single.tsv"
            stale.write_text("stale\n", encoding="utf-8")

            with self.assertRaises(MODULE.NoEstimableEvents):
                MODULE.make_run_evs(
                    "trust", event_file, output_root, clean=True
                )
            self.assertFalse(stale.exists())

    def test_ev_cli_requires_an_explicit_subject_scope(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                MODULE.main(["trust", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)

    def test_ev_cli_supports_external_output_with_dataset_root(self):
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "EVfiles"
            with contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.main(
                    [
                        "ultimatum",
                        "--dataset-root",
                        str(REPO_ROOT / "bids"),
                        "--output-root",
                        str(output_root),
                        "--subject",
                        "144",
                        "--run",
                        "1",
                        "--clean",
                    ]
                )
            self.assertEqual(result, 0)
            evdir = (
                output_root
                / "sub-144/SingleTrialEVs/task-ultimatum/run01"
            )
            self.assertEqual(
                len(list(evdir.glob("trialmodel-*_estimage-single.tsv"))), 72
            )

    def test_runner_dry_run_honors_dataset_subject_and_run_scope(self):
        runner = REPO_ROOT / "code" / "run_L1LSSstats.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            bindir = root / "bin"
            bindir.mkdir()
            fake_nvols = bindir / "fslnvols"
            fake_nvols.write_text(
                "#!/usr/bin/env bash\necho 1\n", encoding="utf-8"
            )
            fake_nvols.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{bindir}:{environment['PATH']}"
            evdir = (
                work
                / "EVfiles/sub-144/SingleTrialEVs"
                / "task-ultimatum/run01"
            )
            evdir.mkdir(parents=True)
            for kind in ("single", "other"):
                (evdir / f"trialmodel-1_estimage-{kind}.tsv").write_text(
                    "1\t1\t1\n", encoding="utf-8"
                )
            unavailable_evdir = (
                work
                / "EVfiles/sub-245/SingleTrialEVs/task-ultimatum/run01"
            )
            unavailable_evdir.mkdir(parents=True)
            for kind in ("single", "other"):
                (unavailable_evdir / f"trialmodel-1_estimage-{kind}.tsv").write_text(
                    "1\t1\t1\n", encoding="utf-8"
                )
            func = root / "derivatives/fmriprep/sub-144/func"
            func.mkdir(parents=True)
            bold = (
                func
                / "sub-144_task-ultimatum_run-1_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            bold.write_text(
                "placeholder", encoding="utf-8"
            )
            confounds = work / "confounds/sub-144"
            confounds.mkdir(parents=True)
            (confounds / "sub-144_task-ultimatum_run-1_desc-fslConfounds.tsv").write_text(
                "0\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    "bash",
                    str(runner),
                    "ultimatum",
                    "--dataset-root",
                    str(root),
                    "--work-root",
                    str(work),
                    "--available-runs",
                    "--jobs",
                    "44",
                    "--all-subjects",
                    "--run",
                    "run-01",
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Selected trial models: 1", result.stdout)
            self.assertIn("Trial models to execute: 1", result.stdout)
            self.assertIn("Concurrent FEAT jobs: 44", result.stdout)
            self.assertIn(
                "Confound/BOLD row counts checked: 1",
                result.stdout,
            )
            self.assertIn(
                "Skipped participant-runs without preprocessed BOLD: 1",
                result.stdout,
            )

            trial_output = (
                work
                / "sub-144"
                / "LSS-images_task-ultimatum_model-01_type-act_run-01"
                / "zstat_trial-01.nii.gz"
            )
            trial_output.parent.mkdir(parents=True)
            trial_output.write_text("complete", encoding="utf-8")
            fingerprint_inputs = (
                evdir / "trialmodel-1_estimage-single.tsv",
                evdir / "trialmodel-1_estimage-other.tsv",
                confounds / "sub-144_task-ultimatum_run-1_desc-fslConfounds.tsv",
                REPO_ROOT / "templates/L1LSS_task-ultimatum_model-01_type-act.fsf",
                REPO_ROOT / "code/L1LSSstats.sh",
            )
            fingerprint = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "code/lss_input_fingerprint.sh"),
                    *(str(path) for path in fingerprint_inputs),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            trial_output.with_name("zstat_trial-01.lss-inputs.cksum").write_text(
                fingerprint, encoding="utf-8"
            )
            refreshed = subprocess.run(
                [
                    "bash",
                    str(runner),
                    "ultimatum",
                    "--dataset-root",
                    str(root),
                    "--work-root",
                    str(work),
                    "--subject",
                    "144",
                    "--run",
                    "1",
                    "--refresh",
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
            self.assertIn("Trial images current with code and inputs: 1", refreshed.stdout)
            self.assertIn("Trial models to execute: 0", refreshed.stdout)

    def test_packer_uses_ev_manifest_and_numeric_trial_order(self):
        packer = REPO_ROOT / "code" / "pack_L1LSSstats.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            evdir = (
                work
                / "EVfiles/sub-144/SingleTrialEVs"
                / "task-ultimatum/run01"
            )
            zdir = (
                work
                / "sub-144"
                / "LSS-images_task-ultimatum_model-01_type-act_run-01"
            )
            bindir = root / "bin"
            evdir.mkdir(parents=True)
            zdir.mkdir(parents=True)
            bindir.mkdir()
            for trial in (1, 2, 10):
                (evdir / f"trialmodel-{trial}_estimage-single.tsv").write_text(
                    "1\t1\t1\n", encoding="utf-8"
                )
                (zdir / f"zstat_trial-{trial:02d}.nii.gz").write_text(
                    str(trial), encoding="utf-8"
                )
            fake_merge = bindir / "fslmerge"
            fake_merge.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$(( $# - 2 ))" > "$2"\n',
                encoding="utf-8",
            )
            fake_nvols = bindir / "fslnvols"
            fake_nvols.write_text(
                '#!/usr/bin/env bash\ncat "$1"\n', encoding="utf-8"
            )
            fake_merge.chmod(0o755)
            fake_nvols.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{bindir}:{environment['PATH']}"
            environment["SRNDNA_DATASET_ROOT"] = str(root)
            environment["SRNDNA_LSS_WORK_ROOT"] = str(work)

            result = subprocess.run(
                ["bash", str(packer), "ultimatum", "144", "1"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = (
                root
                / "derivatives/single_trials/sub-144"
                / "sub-144_task-ultimatum_run-01_singletrial-Act.nii.gz"
            )
            self.assertEqual(output.read_text(encoding="utf-8"), "3\n")

    def test_single_model_runner_uses_separate_dataset_root(self):
        runner = REPO_ROOT / "code" / "L1LSSstats.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "work"
            func = root / "derivatives/fmriprep/sub-144/func"
            confound_dir = work / "confounds/sub-144"
            evdir = (
                work
                / "EVfiles/sub-144/SingleTrialEVs"
                / "task-ultimatum/run01"
            )
            bindir = root / "bin"
            for path in (func, confound_dir, evdir, bindir):
                path.mkdir(parents=True)
            bold = (
                func
                / "sub-144_task-ultimatum_run-1_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            bold.write_text("placeholder", encoding="utf-8")
            (confound_dir / "sub-144_task-ultimatum_run-1_desc-fslConfounds.tsv").write_text(
                "0\n0\n", encoding="utf-8"
            )
            for kind in ("single", "other"):
                (evdir / f"trialmodel-1_estimage-{kind}.tsv").write_text(
                    "1\t1\t1\n", encoding="utf-8"
                )

            fake_nvols = bindir / "fslnvols"
            fake_nvols.write_text("#!/usr/bin/env bash\necho 2\n", encoding="utf-8")
            fake_feat = bindir / "feat"
            fake_feat.write_text(
                "#!/usr/bin/env bash\n"
                "output=$(sed -n 's/^set fmri(outputdir) \"\\(.*\\)\"$/\\1/p' \"$1\")\n"
                "mkdir -p \"${output}.feat/stats\"\n"
                "printf 'zstat\\n' > \"${output}.feat/stats/zstat1.nii.gz\"\n",
                encoding="utf-8",
            )
            fake_nvols.chmod(0o755)
            fake_feat.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{bindir}:{environment['PATH']}"
            environment["SRNDNA_DATASET_ROOT"] = str(root)
            environment["SRNDNA_LSS_WORK_ROOT"] = str(work)

            result = subprocess.run(
                ["bash", str(runner), "144", "1", "1", "ultimatum", "--force"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            trial_output = (
                work
                / "sub-144"
                / "LSS-images_task-ultimatum_model-01_type-act_run-01"
                / "zstat_trial-01.nii.gz"
            )
            self.assertEqual(trial_output.read_text(encoding="utf-8"), "zstat\n")
            self.assertTrue(
                trial_output.with_name("zstat_trial-01.lss-inputs.cksum").is_file()
            )
            self.assertFalse(
                (
                    work
                    / "sub-144"
                    / "L1LSS_task-ultimatum_model-01_type-act_run-01_trial-01.feat"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
