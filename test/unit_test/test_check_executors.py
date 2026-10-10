import importlib.util
import io
import json
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

    def test_queue_report_distinguishes_competitors_isolated_and_unknown(self):
        shared, isolated, unknown = self.m.split_queue_peers(
            ["other", "old", "unknown"],
            ["te.ours.0.common"],
            {"other": ["te.ours.0.common"], "old": ["te.0.common"]},
        )
        self.assertEqual(shared, ["other"])
        self.assertEqual(isolated, ["old"])
        self.assertEqual(unknown, ["unknown"])

    def test_checker_does_not_treat_disjoint_old_workers_as_queue_competitors(self):
        client = Mock()
        client.smembers.return_value = ["task_executor_common_3"]
        client.zrevrange.return_value = [(json.dumps({"task_queues": ["te.0.common", "te.1.common"]}), 1000)]
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"RAGFLOW_TASK_QUEUE_NAMESPACE": "ragflow_python_9380"}, clear=True),
            patch("sys.argv", ["check_executors.py", "--strict"]),
            patch.object(self.m.Path, "read_text", return_value="{}"),
            patch.object(self.m, "redis_client", return_value=client),
            patch.object(self.m.time, "time", return_value=1000),
            redirect_stdout(output),
        ):
            self.assertEqual(self.m.main(), 0)
        self.assertIn("队列已隔离: task_executor_common_3", output.getvalue())
        self.assertNotIn("WARNING", output.getvalue())
        client.delete.assert_not_called()

    def test_expected_ids_must_report_matching_active_queues(self):
        for reported in (["te.0.common", "te.1.common"], None):
            with self.subTest(reported=reported):
                client = Mock()
                client.smembers.return_value = ["task_executor_common_6"]
                client.zrevrange.return_value = [(json.dumps({"task_queues": reported}), 1000)]
                output = io.StringIO()
                with (
                    patch.dict(os.environ, {"RAGFLOW_TASK_QUEUE_NAMESPACE": "ragflow_python_9380"}, clear=True),
                    patch("sys.argv", ["check_executors.py", "--strict"]),
                    patch.object(self.m.Path, "read_text", return_value="{}"),
                    patch.object(self.m, "redis_client", return_value=client),
                    patch.object(self.m.time, "time", return_value=1000),
                    redirect_stdout(output),
                ):
                    self.assertEqual(self.m.main(), 1)
                self.assertNotIn("未发现外部执行器竞争队列", output.getvalue())
                client.delete.assert_not_called()

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
