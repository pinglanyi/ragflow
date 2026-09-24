"""Focused tests for Redis queue publishing resilience."""

import ast
import json
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[2]


class RedisQueueTest(unittest.TestCase):
    def test_queue_product_backs_off_between_transient_failures(self):
        tree = ast.parse((ROOT / "rag/utils/redis_conn.py").read_text(encoding="utf-8"))
        redis_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RedisDB")
        method = next(node for node in redis_class.body if isinstance(node, ast.FunctionDef) and node.name == "queue_product")
        namespace = {"json": json, "logging": types.SimpleNamespace(exception=Mock()), "sleep": Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<queue-product>", "exec"), namespace)

        redis = Mock()
        redis.xadd.side_effect = [ConnectionError("starting"), ConnectionError("starting"), ConnectionError("starting"), "message-id"]
        owner = types.SimpleNamespace(REDIS=redis)
        setattr(owner, "__open__", Mock())

        self.assertTrue(namespace["queue_product"](owner, "queue", {"id": "task"}))
        self.assertEqual(redis.xadd.call_count, 4)
        self.assertEqual(namespace["sleep"].call_args_list, [unittest.mock.call(1), unittest.mock.call(2), unittest.mock.call(4)])

    def test_chunking_counter_seed_backs_off_until_redis_recovers(self):
        tree = ast.parse((ROOT / "api/db/services/task_service.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "seed_doc_chunking_counter")
        redis = Mock()
        redis.delete.return_value = True
        redis.set.side_effect = [False, False, False, True]
        namespace = {
            "REDIS_CONN": redis,
            "DOC_CHUNKING_COUNTER_TTL_SECONDS": 60,
            "_doc_chunking_aborted_key": lambda doc_id: f"aborted:{doc_id}",
            "_doc_chunking_pending_key": lambda doc_id: f"pending:{doc_id}",
            "logging": types.SimpleNamespace(exception=Mock()),
            "sleep": Mock(),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<seed-counter>", "exec"), namespace)

        self.assertTrue(namespace["seed_doc_chunking_counter"]("doc", 2))
        self.assertEqual(redis.set.call_count, 4)
        self.assertEqual(namespace["sleep"].call_args_list, [unittest.mock.call(1), unittest.mock.call(2), unittest.mock.call(4)])

    def test_submission_uses_dispatch_snapshot_returned_by_queueing(self):
        service_tree = ast.parse((ROOT / "api/apps/services/multimodal_api_service.py").read_text(encoding="utf-8"))
        submit = next(node for node in service_tree.body if isinstance(node, ast.FunctionDef) and node.name == "submit")
        submit_code = ast.unparse(submit)
        self.assertIn("current = DocumentService.run", submit_code)

        document_tree = ast.parse((ROOT / "api/db/services/document_service.py").read_text(encoding="utf-8"))
        document_class = next(node for node in document_tree.body if isinstance(node, ast.ClassDef) and node.name == "DocumentService")
        run = next(node for node in document_class.body if isinstance(node, ast.FunctionDef) and node.name == "run")
        self.assertIn("return queue_tasks", ast.unparse(run))

    def test_uploaded_binary_bypasses_immediate_storage_read(self):
        tree = ast.parse((ROOT / "api/db/services/task_service.py").read_text(encoding="utf-8"))
        helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_document_binary")
        storage = Mock()
        namespace = {"settings": types.SimpleNamespace(STORAGE_IMPL=storage)}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "<document-binary>", "exec"), namespace)

        doc = {"_uploaded_binary": b"PK\x03\x04xlsx"}
        self.assertEqual(namespace["_document_binary"](doc, "bucket", "file.xlsx"), b"PK\x03\x04xlsx")
        storage.get.assert_not_called()
        self.assertNotIn("_uploaded_binary", doc)

        storage.get.return_value = b"stored"
        self.assertEqual(namespace["_document_binary"]({}, "bucket", "file.xlsx"), b"stored")
        storage.get.assert_called_once_with("bucket", "file.xlsx")


if __name__ == "__main__":
    unittest.main()
