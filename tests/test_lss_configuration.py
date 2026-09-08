import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "code" / "makeSingleTrials_trust.py"
SPEC = importlib.util.spec_from_file_location("make_trust_lss", SCRIPT)
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

            trial_count = MODULE.make_run_evs(event_file, output_root, clean=True)

            self.assertEqual(trial_count, 34)
            self.assertFalse(stale.exists())
            single = output_dir / "trialmodel-1_estimage-single.tsv"
            other = output_dir / "trialmodel-1_estimage-other.tsv"
            self.assertEqual(len(single.read_text().splitlines()), 1)
            self.assertEqual(len(other.read_text().splitlines()), 33)


if __name__ == "__main__":
    unittest.main()
