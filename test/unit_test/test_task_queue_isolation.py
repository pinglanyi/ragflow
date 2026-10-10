"""Verify queue routing without Redis or database dependencies."""

import ast
import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class TaskQueueIsolationTests(unittest.TestCase):
    def setUp(self):
        self.queues = importlib.import_module("common.task_queue")
        source = ast.parse((ROOT / "common/settings.py").read_text(encoding="utf-8"))
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in {"get_svr_queue_name", "get_svr_queue_names"}]
        self.settings = {"SVR_QUEUE_NAME": "te", "task_queue_name": self.queues.task_queue_name}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "settings.py", "exec"), self.settings)  # noqa: S102 - trusted repository functions

    def test_existing_launches_keep_their_queues(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.settings["get_svr_queue_names"]("common"), ["te.1.common", "te.0.common"])

    def test_api_producer_and_worker_consumer_use_same_isolated_stream(self):
        with patch.dict(os.environ, {"RAGFLOW_TASK_QUEUE_NAMESPACE": "ragflow_python_9380"}, clear=True):
            for priority in (0, 1):
                producer = self.settings["get_svr_queue_name"](priority, "common")
                consumers = self.settings["get_svr_queue_names"]("common")
                self.assertIn(producer, consumers)
                self.assertEqual(producer, f"te.ragflow_python_9380.{priority}.common")
            self.assertEqual(self.queues.task_queue_names(), consumers)

    def test_old_workers_cannot_see_new_queue_messages(self):
        with patch.dict(os.environ, {}, clear=True):
            old = set(self.settings["get_svr_queue_names"]("common"))
        with patch.dict(os.environ, {"RAGFLOW_TASK_QUEUE_NAMESPACE": "ragflow_python_9380"}, clear=True):
            new = set(self.settings["get_svr_queue_names"]("common"))
        self.assertFalse(old & new)

    def test_task_types_preserve_existing_shared_common_queue(self):
        with patch.dict(os.environ, {"RAGFLOW_TASK_QUEUE_NAMESPACE": "isolated"}, clear=True):
            self.assertEqual(self.settings["get_svr_queue_names"]("graphrag"), self.settings["get_svr_queue_names"]("common"))

    def test_unsafe_namespace_is_rejected(self):
        for namespace in ("with space", "other.queue", "../legacy", "a" * 81):
            with self.subTest(namespace=namespace), patch.dict(os.environ, {"RAGFLOW_TASK_QUEUE_NAMESPACE": namespace}), self.assertRaises(ValueError):
                self.queues.task_queue_name(0)


if __name__ == "__main__":
    unittest.main()
