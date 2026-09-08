import importlib.util
import hashlib
import sys
import unittest
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "code" / "recover_sub144_ultimatum_events.py"
SPEC = importlib.util.spec_from_file_location("recover_sub144", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RecoverSub144UltimatumTests(unittest.TestCase):
    def test_converter_matches_historical_first_session_outputs(self):
        expected_hashes = {
            0: "5491a2d2db11787d57c40ed6ec1d63ed1256e6c0276400f519e57bc5459608b7",
            1: "467069b092d73c11ce1a0740b3ac43f8a4f791cff5d71ceb0cd0cb44e6468c01",
        }
        for raw_run, expected_hash in expected_hashes.items():
            path = (
                REPO_ROOT
                / "stimuli"
                / "psychopy"
                / "logs"
                / "144"
                / f"sub-144_task-ultimatum_run-{raw_run}_raw.csv"
            )
            session = MODULE.read_logged_sessions(path)[0]
            rendered = MODULE.render_tsv(MODULE.make_event_rows(session)).encode()
            self.assertEqual(hashlib.sha256(rendered).hexdigest(), expected_hash)

    def test_raw_logs_contain_two_complete_sessions(self):
        for raw_run in (0, 1):
            path = (
                REPO_ROOT
                / "stimuli"
                / "psychopy"
                / "logs"
                / "144"
                / f"sub-144_task-ultimatum_run-{raw_run}_raw.csv"
            )
            sessions = MODULE.read_logged_sessions(path)
            self.assertEqual([len(session) for session in sessions], [72, 72])
            self.assertNotEqual(
                [row["resp"] for row in sessions[0]],
                [row["resp"] for row in sessions[1]],
            )

    def test_second_session_generates_expected_event_counts(self):
        expected = {
            0: {"rows": 215, "missed_trial": 1, "event_RT": 63},
            1: {"rows": 216, "missed_trial": 0, "event_RT": 63},
        }
        for raw_run, expectation in expected.items():
            path = (
                REPO_ROOT
                / "stimuli"
                / "psychopy"
                / "logs"
                / "144"
                / f"sub-144_task-ultimatum_run-{raw_run}_raw.csv"
            )
            rows = MODULE.make_event_rows(MODULE.read_logged_sessions(path)[1])
            counts = Counter(row[2] for row in rows)
            self.assertEqual(len(rows), expectation["rows"])
            self.assertEqual(counts["missed_trial"], expectation["missed_trial"])
            self.assertEqual(counts["event_RT"], expectation["event_RT"])
            self.assertEqual(sum(name.startswith("block_") for name in counts), 6)
            self.assertEqual(sum(count for name, count in counts.items() if name.startswith("block_")), 9)

    def test_all_tracked_copies_are_current(self):
        self.assertEqual(MODULE.rebuild(REPO_ROOT, check=True), 0)


if __name__ == "__main__":
    unittest.main()
