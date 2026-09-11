import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CheckExecutorsTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "scripts/check_executors.py"
        self.assertTrue(source.exists(), "Executor conflict checker is missing")
        spec = importlib.util.spec_from_file_location("check_executors", source)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_expected_executors_follows_start_sh_defaults(self):
        names = self.m.expected_executors(["common"], 3, 3)
        self.assertEqual(names, {"task_executor_common_3", "task_executor_common_4", "task_executor_common_5"})

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
