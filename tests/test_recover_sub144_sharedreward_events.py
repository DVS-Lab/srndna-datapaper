import hashlib
import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "code" / "recover_sub144_sharedreward_events.py"
SPEC = importlib.util.spec_from_file_location("recover_sub144_sharedreward", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RecoverSub144SharedRewardTests(unittest.TestCase):
    def test_converter_matches_published_sub143_session(self):
        expected_hashes = {
            0: "5a7762761b4193e30e0b1b557850ee46279b249bd0103b6487549c52b9e9da6f",
            1: "e778954c147f0c2e62f34f06678fb9f8ac9665cb6d0bddb536ca2f0fb0a2bd0f",
        }
        for raw_run, expected_hash in expected_hashes.items():
            path = (
                REPO_ROOT
                / "stimuli"
                / "psychopy"
                / "logs"
                / "144"
                / f"sub-144_task-sharedreward_run-{raw_run}_raw.csv"
            )
            rendered = MODULE.render_tsv(
                MODULE.make_event_rows(MODULE.read_logged_sessions(path)[0])
            ).encode()
            self.assertEqual(hashlib.sha256(rendered).hexdigest(), expected_hash)
            published = (
                REPO_ROOT
                / "bids"
                / "sub-143"
                / "func"
                / f"sub-143_task-sharedreward_run-{raw_run + 1:02d}_events.tsv"
            )
            self.assertEqual(hashlib.sha256(published.read_bytes()).hexdigest(), expected_hash)

    def test_raw_logs_contain_two_distinct_complete_sessions(self):
        for raw_run in (0, 1):
            path = (
                REPO_ROOT
                / "stimuli"
                / "psychopy"
                / "logs"
                / "144"
                / f"sub-144_task-sharedreward_run-{raw_run}_raw.csv"
            )
            sessions = MODULE.read_logged_sessions(path)
            self.assertEqual([len(session) for session in sessions], [72, 72])
            self.assertNotEqual(
                [row["rt"] for row in sessions[0]],
                [row["rt"] for row in sessions[1]],
            )

    def test_second_session_generates_expected_event_counts(self):
        expected_missed = {0: 1, 1: 0}
        for raw_run, missed in expected_missed.items():
            path = (
                REPO_ROOT
                / "stimuli"
                / "psychopy"
                / "logs"
                / "144"
                / f"sub-144_task-sharedreward_run-{raw_run}_raw.csv"
            )
            rows = MODULE.make_event_rows(MODULE.read_logged_sessions(path)[1])
            counts = Counter(row[2] for row in rows)
            self.assertEqual(len(rows), 81)
            self.assertEqual(counts["missed_trial"], missed)
            self.assertEqual(
                sum(count for name, count in counts.items() if name.startswith("block_")),
                9,
            )

    def test_tracked_outputs_are_current(self):
        self.assertEqual(MODULE.rebuild(REPO_ROOT, check=True), 0)


if __name__ == "__main__":
    unittest.main()
