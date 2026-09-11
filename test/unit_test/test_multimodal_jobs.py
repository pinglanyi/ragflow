"""SQLite tests of the actual job model/service without booting RAGFlow servers."""
# ruff: noqa: S102 -- execute only trusted repository AST to isolate external services

import ast
import hashlib
import importlib.util
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import peewee as pw
from playhouse.sqlite_ext import JSONField

ROOT = Path(__file__).resolve().parents[2]


class JobsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = pw.SqliteDatabase(str(Path(cls.tmp.name) / "jobs.sqlite"))
        lock = threading.RLock()
        db.lock = lambda *args: lock
        cls.db = db

        class Base(pw.Model):
            class Meta:
                database = db

        class Document(Base):
            id = pw.CharField(primary_key=True)
            run = pw.CharField(default="1")
            progress = pw.FloatField(default=0)

        class Task(Base):
            id = pw.CharField(primary_key=True)
            doc_id = pw.CharField()
            progress = pw.FloatField(default=0)
            progress_msg = pw.TextField(default="")
            chunk_ids = pw.TextField(default="")
            retry_count = pw.IntegerField(default=0)

        tree = ast.parse((ROOT / "api/db/db_models.py").read_text(encoding="utf-8"))
        node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MultimodalJob"), None)
        assert node is not None, "MultimodalJob durable model is missing"
        ns = dict(vars(pw), DataBaseModel=Base, JSONField=JSONField)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<real-job-model>", "exec"), ns)
        cls.Job, cls.Task, cls.Document = ns["MultimodalJob"], Task, Document
        fake = types.ModuleType("api.db.db_models")
        fake.DB, fake.MultimodalJob, fake.Task, fake.Document = db, cls.Job, Task, Document
        cls.old = sys.modules.get("api.db.db_models")
        sys.modules["api.db.db_models"] = fake
        path = ROOT / "api/db/services/multimodal_job_service.py"
        spec = importlib.util.spec_from_file_location("tested_mm_jobs", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        cls.mod._signal_cancel = Mock()
        cls.svc = cls.mod.MultimodalJobService
        db.create_tables([cls.Job, Task, Document])

    @classmethod
    def tearDownClass(cls):
        if cls.old:
            sys.modules["api.db.db_models"] = cls.old
        else:
            sys.modules.pop("api.db.db_models", None)
        cls.db.close()
        cls.tmp.cleanup()

    def setUp(self):
        for model in (self.Job, self.Task, self.Document):
            model.delete().execute()
        self.Document.create(id="doc")
        self.job = self.svc.create("tenant", "kb", "doc", {"multimodal": {"enabled": True, "model": "vision"}})

    def child(self, id="a", progress=0, chunks=""):
        self.Task.create(id=id, doc_id="doc", progress=progress, chunk_ids=chunks)

    def test_config_inherits_and_overrides(self):
        cfg = self.mod.build_config({"ext": {"multimodal": {"model": "kb"}}}, {"multimodal": {"prompt": "doc"}}, {"reuse": False}, "x.pdf")
        self.assertEqual(cfg["multimodal"]["model"], "kb")
        self.assertEqual(cfg["multimodal"]["prompt"], "doc")
        self.assertFalse(cfg["multimodal"]["reuse"])
        self.assertFalse(cfg["parent_child"]["use_parent_child"])

    def test_invalid_config(self):
        for options in ({"enabled": False}, {"max_tokens": True}, {"max_tokens": 12}, {"reuse": "false"}, {"api_key": "secret"}, {"prompt": None}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.mod.build_config({}, {"multimodal": {"model": "m"}}, options, "x.pdf")
        for name in ("x.mp4", "x.docx", ""):
            with self.assertRaises(ValueError):
                self.mod.build_config({}, {}, {}, name)

    def test_complete_requires_all_children_and_dispatch(self):
        self.child(progress=1, chunks="c1")
        self.child("b", 0, "")
        self.svc.bind_tasks(self.job.id, ["a", "b"])
        self.assertNotEqual(self.svc.refresh(self.job.id).status, "complete")
        self.svc.mark_dispatched(self.job.id)
        self.assertNotEqual(self.svc.refresh(self.job.id).status, "complete")
        self.Task.update(progress=1, chunk_ids="c2").where(self.Task.id == "b").execute()
        result = self.svc.refresh(self.job.id)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.chunk_count, 2)

    def test_no_complete_before_queue_publication(self):
        self.child(progress=1, chunks="c")
        self.svc.bind_tasks(self.job.id, ["a"])
        self.assertNotEqual(self.svc.refresh(self.job.id).status, "complete")

    def test_empty_output_fails(self):
        self.child(progress=1)
        self.svc.bind_tasks(self.job.id, ["a"])
        self.svc.mark_dispatched(self.job.id)
        self.assertEqual(self.svc.refresh(self.job.id).status, "failed")

    def test_partial_error_fails(self):
        self.child(progress=-1)
        self.child("b", 1, "c")
        self.svc.bind_tasks(self.job.id, ["a", "b"])
        self.svc.mark_dispatched(self.job.id)
        self.assertEqual(self.svc.refresh(self.job.id).status, "failed")

    def test_cancelled_document(self):
        self.child()
        self.svc.bind_tasks(self.job.id, ["a"])
        self.svc.mark_dispatched(self.job.id)
        self.Document.update(run="2").execute()
        self.assertEqual(self.svc.refresh(self.job.id).status, "cancelled")

    def test_native_reparse_keeps_old_terminal_status(self):
        self.child(progress=1, chunks="c")
        self.svc.bind_tasks(self.job.id, ["a"])
        self.svc.mark_dispatched(self.job.id)
        self.svc.before_delete(["a"])
        self.Task.delete().execute()
        self.child("new", 0)
        self.assertEqual(self.svc.refresh(self.job.id).status, "complete")

    def test_native_reparse_cancels_active_job(self):
        self.child()
        self.svc.bind_tasks(self.job.id, ["a"])
        self.svc.mark_dispatched(self.job.id)
        self.svc.before_delete(["a"])
        self.Task.delete().execute()
        self.child("new", 1, "c")
        self.assertEqual(self.svc.refresh(self.job.id).status, "cancelled")

    def test_missing_tasks_cannot_complete(self):
        self.svc.bind_tasks(self.job.id, ["gone"])
        self.svc.mark_dispatched(self.job.id)
        self.assertEqual(self.svc.refresh(self.job.id).status, "cancelled")

    def test_tenant_isolation(self):
        self.assertIsNone(self.svc.get_owned(self.job.id, "another"))
        self.assertEqual(self.svc.get_owned(self.job.id, "tenant").id, self.job.id)

    def test_unique_claim_released_only_on_terminal(self):
        with self.assertRaises(pw.IntegrityError):
            self.svc.create("tenant", "kb", "doc", {})
        self.svc.fail(self.job.id, "test", "failed")
        other = self.svc.create("tenant", "kb", "doc", {})
        self.assertNotEqual(other.id, self.job.id)

    def test_concurrent_submissions_only_one_claim(self):
        from concurrent.futures import ThreadPoolExecutor

        self.Job.delete().execute()
        barrier = threading.Barrier(2)

        def claim():
            with self.db.connection_context():
                barrier.wait()
                try:
                    self.svc.create("tenant", "kb", "doc", {})
                    return "accepted"
                except pw.IntegrityError:
                    return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertCountEqual(results, ["accepted", "conflict"])

    def test_stale_update_cannot_resurrect_cancelled_job(self):
        self.svc._update(self.job.id, status="cancelled")
        self.svc._update(self.job.id, status="running")
        self.assertEqual(self.Job.get_by_id(self.job.id).status, "cancelled")

    def test_failure_aborts_unfinished_siblings(self):
        self.child(progress=-1)
        self.child("b", 0, "")
        self.svc.bind_tasks(self.job.id, ["a", "b"])
        self.svc.mark_dispatched(self.job.id)
        self.assertEqual(self.Task.get_by_id("b").progress, -1)

    def test_interrupted_dispatch_releases_stale_document_flag(self):
        self.Job.update(created_at="2020-01-01T00:00:00+00:00").execute()
        result = self.svc.refresh(self.job.id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.Document.get_by_id("doc").run, "4")
        self.assertIsNone(result.active_document_id)

    def test_real_queue_binds_before_worker_and_waits_for_publication(self):
        tree = ast.parse((ROOT / "api/db/services/task_service.py").read_text(encoding="utf-8"))
        queue = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "queue_tasks")

        class StripImports(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                return None

        queue = StripImports().visit(queue)
        docs = Mock()
        docs.get_chunking_config.return_value = {"tenant_id": "tenant", "kb_id": "kb", "parser_config": {}}
        task_service = Mock()
        task_service.get_tasks.return_value = []
        store = Mock()
        store.index_exist.return_value = False

        def bulk_insert(model, values, ignored):
            for item in values:
                self.Task.create(id=item["id"], doc_id=item["doc_id"], progress=item["progress"])

        def publish(name, message):
            self.assertEqual(self.Job.get_by_id(self.job.id).task_ids, [message["id"]])
            self.Task.update(progress=1, chunk_ids="c1").where(self.Task.id == message["id"]).execute()
            self.assertNotEqual(self.svc.refresh(self.job.id).status, "complete")
            return True

        ns = {
            "datetime": datetime,
            "get_uuid": lambda: "child",
            "MAXIMUM_TASK_PAGE_NUMBER": 100000,
            "FileType": types.SimpleNamespace(PDF=types.SimpleNamespace(value="pdf")),
            "DocumentService": docs,
            "TaskService": task_service,
            "Task": self.Task,
            "settings": types.SimpleNamespace(docStoreConn=store, get_svr_queue_name=lambda *a: "queue"),
            "xxhash": types.SimpleNamespace(xxh64=hashlib.md5),
            "MultimodalJobService": self.svc,
            "search": types.SimpleNamespace(index_name=lambda x: x),
            "bulk_insert_into_db": bulk_insert,
            "seed_doc_chunking_counter": lambda *a: True,
            "abort_doc_chunking_counter": Mock(),
            "REDIS_CONN": types.SimpleNamespace(queue_product=publish),
        }
        exec(compile(ast.Module(body=[queue], type_ignores=[]), "<real-queue>", "exec"), ns)
        ns["queue_tasks"]({"id": "doc", "kb_id": "kb", "type": "visual", "parser_id": "picture", "_multimodal_job_id": self.job.id}, "bucket", "name", 0)
        self.assertEqual(self.svc.refresh(self.job.id).status, "complete")

    def test_snapshot_used_by_worker(self):
        self.child()
        self.svc.bind_tasks(self.job.id, ["a"])
        task = {"id": "a", "doc_id": "doc", "parser_config": {"multimodal": {"enabled": False}}, "kb_parser_config": {}}
        prepared = self.svc.prepare_task(task)
        self.assertTrue(prepared["parser_config"]["multimodal"]["enabled"])

    def test_terminal_delivery_rejected_before_native_progress_update(self):
        tree = ast.parse((ROOT / "api/db/services/task_service.py").read_text(encoding="utf-8"))
        klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TaskService")
        method = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "get_task")
        code = ast.unparse(method)
        self.assertLess(code.index("prepare_task(doc)"), code.index("cls.model.update("))
        method.decorator_list = []

        class StripImports(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                return None

        method = StripImports().visit(method)
        from unittest.mock import MagicMock

        query = MagicMock()
        query.join.return_value = query
        query.where.return_value = query
        query.dicts.return_value = [{"id": "a", "doc_id": "doc", "retry_count": 0}]
        model = MagicMock()
        model.select.return_value = query
        cls = types.SimpleNamespace(model=model)
        ns = {"MultimodalJobService": self.svc, "Document": MagicMock(), "Knowledgebase": MagicMock(), "Tenant": MagicMock(), "CANVAS_DEBUG_DOC_ID": "debug"}
        self.child()
        self.svc.bind_tasks(self.job.id, ["a"])
        self.svc.fail(self.job.id, "test", "failed")
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<real-get-task>", "exec"), ns)
        self.assertIsNone(ns["get_task"](cls, "a"))
        model.update.assert_not_called()

    def test_failure_between_prepare_and_claim_does_not_revive_child(self):
        import random
        from unittest.mock import MagicMock

        tree = ast.parse((ROOT / "api/db/services/task_service.py").read_text(encoding="utf-8"))
        klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TaskService")
        method = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "get_task")
        method.decorator_list = []

        class StripImports(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                return None

        method = StripImports().visit(method)
        self.child()
        self.svc.bind_tasks(self.job.id, ["a"])
        query = MagicMock()
        query.join.return_value = query
        query.where.return_value = query
        query.dicts.return_value = [{"id": "a", "doc_id": "doc", "retry_count": 0, "type": "pdf"}]
        model = MagicMock()
        model.select.return_value = query
        model.update = self.Task.update
        model.id = self.Task.id
        model.progress = self.Task.progress
        model.progress_msg = self.Task.progress_msg

        def prepare(task):
            task = self.svc.prepare_task(task)
            self.svc.fail(self.job.id, "test", "failed during claim")
            return task

        ns = {
            "MultimodalJobService": types.SimpleNamespace(prepare_task=prepare),
            "Document": MagicMock(),
            "Knowledgebase": MagicMock(),
            "Tenant": MagicMock(),
            "CANVAS_DEBUG_DOC_ID": "debug",
            "datetime": datetime,
            "random": random,
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<real-get-task-race>", "exec"), ns)
        self.assertIsNone(ns["get_task"](types.SimpleNamespace(model=model), "a"))
        self.assertEqual(self.Task.get_by_id("a").progress, -1)

    def test_stale_worker_cannot_write_after_failure(self):
        self.child()
        self.svc.bind_tasks(self.job.id, ["a"])
        self.svc.mark_dispatched(self.job.id)
        store = Mock(return_value=[])
        self.assertTrue(hasattr(self.mod, "guarded_insert"), "guarded_insert is missing")
        self.mod.guarded_insert("a", [{"doc_id": "doc", "id": "c"}], "idx", "kb", store)
        self.assertEqual(store.call_count, 1)
        self.svc.fail(self.job.id, "test", "failed")
        with self.assertRaises(RuntimeError):
            self.mod.guarded_insert("a", [{"doc_id": "doc", "id": "c"}], "idx", "kb", store)
        self.assertEqual(store.call_count, 1)

    def test_failed_dispatch_does_not_complete(self):
        self.child(progress=1, chunks="c")
        self.svc.bind_tasks(self.job.id, ["a"])
        self.svc.fail(self.job.id, "dispatch_error", "Cannot publish all tasks")
        self.assertEqual(self.svc.refresh(self.job.id).status, "failed")

    def test_hooks_bind_before_publish_and_finish_after_publish(self):
        source = (ROOT / "api/db/services/task_service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        queue = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "queue_tasks")
        code = ast.unparse(queue)
        self.assertIn("bind_tasks", code)
        self.assertLess(code.index("bind_tasks"), code.index("queue_product"))
        self.assertGreater(code.index("mark_dispatched"), code.index("queue_product"))
        self.assertIn("prepare_task(doc)", source)
        self.assertIn("refresh_document(task.doc_id)", source)
        self.assertIn("before_delete", source)

    def submission_service(self):
        path = ROOT / "api/apps/services/multimodal_api_service.py"
        self.assertTrue(path.exists(), "Submission service is missing")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
        kb = types.SimpleNamespace(id="kb", parser_config={"multimodal": {"model": "m"}}, pipeline_id="")
        doc = types.SimpleNamespace(id="doc", name="x.pdf", parser_config={}, pipeline_id="", run="0")
        doc.to_dict = lambda: {"id": "doc", "name": doc.name, "parser_config": doc.parser_config, "type": "pdf", "parser_id": "naive", "pipeline_id": ""}
        docs = Mock()
        docs.query.return_value = [doc]
        kbs = Mock()
        kbs.query.return_value = [kb]
        resolver = Mock(return_value={"api_base": "http://model/v1"})
        ns = {
            "DB": self.db,
            "Task": self.Task,
            "Jobs": self.svc,
            "MultimodalJob": self.Job,
            "DocumentService": docs,
            "KnowledgebaseService": kbs,
            "FileService": Mock(),
            "resolve_model_config": resolver,
            "LLMType": types.SimpleNamespace(VISION="vision"),
            "build_config": self.mod.build_config,
            "Path": Path,
            "logging": __import__("logging"),
            "IntegrityError": pw.IntegrityError,
        }
        exec(compile(tree, str(path), "exec"), ns)
        return types.SimpleNamespace(**ns), doc

    def test_submission_rejects_native_busy_before_mutation(self):
        service, _doc = self.submission_service()
        self.Job.delete().execute()
        self.child()
        with self.assertRaises(service.ApiError) as err:
            service.submit("tenant", "kb", "doc", {})
        self.assertEqual(err.exception.status, 409)
        service.DocumentService.update_by_id.assert_not_called()

    def test_submission_rejects_invalid_model(self):
        service, _doc = self.submission_service()
        self.Job.delete().execute()
        service.resolve_model_config.side_effect = LookupError("not vision")
        with self.assertRaises(service.ApiError):
            service.submit("tenant", "kb", "doc", {})
        service.DocumentService.update_by_id.assert_not_called()

    def test_submission_dispatch_failure_persisted(self):
        service, _doc = self.submission_service()
        self.Job.delete().execute()
        service.DocumentService.run.side_effect = RuntimeError("secret detail")
        with self.assertLogs(level="ERROR"), self.assertRaises(service.ApiError) as err:
            service.submit("tenant", "kb", "doc", {})
        self.assertEqual(err.exception.status, 503)
        self.assertEqual(self.Job.get().status, "failed")
        self.assertNotIn("secret", str(err.exception))
        service.DocumentService.clear_chunk_num_when_rerun.assert_called_once_with("doc")

    def test_submission_success_snapshot_and_queued_response(self):
        service, _doc = self.submission_service()
        self.Job.delete().execute()

        def run(tenant, task_doc, tables):
            job_id = task_doc["_multimodal_job_id"]
            self.assertTrue(task_doc["parser_config"]["multimodal"]["enabled"])
            self.child()
            self.svc.bind_tasks(job_id, ["a"])
            self.svc.mark_dispatched(job_id)

        service.DocumentService.run.side_effect = run
        result = service.submit("tenant", "kb", "doc", {"reuse": False})
        self.assertEqual(result["status"], "queued")
        self.assertTrue(result["task_id"])
        self.assertFalse(self.Job.get().config["multimodal"]["reuse"])

    def test_upload_failure_after_saving_returns_document_id(self):
        service, _doc = self.submission_service()
        service.FileService.upload_document.return_value = ([], [({"id": "doc"}, b"data")])
        # Existing active custom job will reject submission after successful upload.
        with self.assertRaises(service.ApiError) as err:
            service.upload("tenant", "kb", types.SimpleNamespace(filename="x.pdf"), {})
        self.assertEqual(err.exception.data["document_id"], "doc")

    def test_upload_invalid_model_does_not_store_file(self):
        service, _doc = self.submission_service()
        service.resolve_model_config.side_effect = LookupError("no vision")
        with self.assertRaises(service.ApiError):
            service.upload("tenant", "kb", types.SimpleNamespace(filename="x.pdf"), {})
        service.FileService.upload_document.assert_not_called()

    def test_submission_rejects_pipeline(self):
        service, doc = self.submission_service()
        doc.pipeline_id = "custom"
        with self.assertRaises(service.ApiError) as err:
            service.submit("tenant", "kb", "doc", {})
        self.assertEqual(err.exception.status, 409)

    def test_submission_unknown_kb_is_404(self):
        service, _doc = self.submission_service()
        service.KnowledgebaseService.query.return_value = []
        with self.assertRaises(service.ApiError) as err:
            service.submit("tenant", "kb", "doc", {})
        self.assertEqual(err.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
