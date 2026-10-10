import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


class CheckExecutorsTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "scripts/check_executors.py"
        self.assertTrue(source.exists(), "Executor conflict checker is missing")
        spec = importlib.util.spec_from_file_location("check_executors", source)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_expected_executors_keeps_explicit_old_offset_supported(self):
        names = self.m.expected_executors(["common"], 3, 3)
        self.assertEqual(names, {"task_executor_common_3", "task_executor_common_4", "task_executor_common_5"})

    def test_cli_defaults_match_new_shell_ids(self):
        client = Mock()
        client.smembers.return_value = []
        output = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["check_executors.py"]),
            patch.object(self.m.Path, "read_text", return_value="{}"),
            patch.object(self.m, "redis_client", return_value=client),
            redirect_stdout(output),
        ):
            self.assertEqual(self.m.main(), 0)
        self.assertIn("task_executor_common_6, task_executor_common_7, task_executor_common_8", output.getvalue())

    def test_expected_executors_covers_several_types(self):
        names = self.m.expected_executors(["common", "graphrag"], 2, 0)
        self.assertEqual(len(names), 4)
        self.assertIn("task_executor_graphrag_1", names)

    def test_heartbeat_age_accepts_milliseconds_and_seconds(self):
        now = 1_800_000_000.0
        self.assertAlmostEqual(30.0, self.m.heartbeat_age([(now - 30) * 1000], now), places=3)
        self.assertAlmostEqual(30.0, self.m.heartbeat_age([now - 30], now), places=3)
        self.assertIsNone(self.m.heartbeat_age([], now))

    def test_heartbeat_age_never_goes_negative(self):
        now = 1_800_000_000.0
        self.assertEqual(0.0, self.m.heartbeat_age([(now + 60) * 1000], now))

    def test_classify_separates_ours_live_and_stale(self):
        expected = {"task_executor_common_3", "task_executor_common_4", "task_executor_common_5"}
        members = {"task_executor_common_3", "task_executor_f4003e4d3cfa_0", "task_executor_2"}
        ages = {"task_executor_common_3": 5.0, "task_executor_f4003e4d3cfa_0": 20.0, "task_executor_2": 9_000.0}
        ours, live, stale = self.m.classify(members, expected, ages, stale_after=120)
        self.assertEqual(ours, ["task_executor_common_3"])
        self.assertEqual(live, ["task_executor_f4003e4d3cfa_0"])
        self.assertEqual(stale, ["task_executor_2"])

    def test_unreported_executor_counts_as_residue(self):
        members = {"task_executor_1"}
        ours, live, stale = self.m.classify(members, set(), {}, stale_after=120)
        self.assertEqual([], ours)
        self.assertEqual([], live)
        self.assertEqual(["task_executor_1"], stale)


if __name__ == "__main__":
    unittest.main()
