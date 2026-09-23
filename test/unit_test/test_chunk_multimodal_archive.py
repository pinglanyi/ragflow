import importlib.util
import ast
import asyncio
import json
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("chunk_multimodal", Path(__file__).resolve().parents[2] / "rag/svr/chunk_multimodal.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sync_spec = importlib.util.spec_from_file_location("archive_sync", Path(__file__).resolve().parents[2] / "scripts/multimodal_archive.py")
sync = importlib.util.module_from_spec(sync_spec)
sync_spec.loader.exec_module(sync)


def response(content="# Motor\n\n| Model | Power |\n| --- | --- |\n| A | 10 kW |", finish="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": {"total_tokens": 12}}


class ArchiveTest(unittest.TestCase):
    def test_picture_direct_mode_skips_ocr_and_defers_model_call(self):
        import io
        import re
        from PIL import Image, ImageOps
        from unittest.mock import Mock
        source = Path(__file__).resolve().parents[2] / "rag/app/picture.py"
        func = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef) and n.name == "chunk")
        namespace = {"io": io, "re": re, "Image": Image, "ImageOps": ImageOps, "VIDEO_EXTS": [".mp4"],
                     "rag_tokenizer": types.SimpleNamespace(tokenize=lambda s: s),
                     "_try_paddleocr_image": Mock(side_effect=AssertionError("OCR must not run")),
                     "tokenize": lambda doc, text, *a, **kw: doc.update(content_with_weight=text)}
        exec(compile(ast.Module(body=[func], type_ignores=[]), str(source), "exec"), namespace)
        png = io.BytesIO()
        Image.new("RGB", (24, 24)).save(png, format="PNG")
        result = namespace["chunk"]("CAN接线图.png", png.getvalue(), "tenant", "Chinese", parser_config={"multimodal": {"enabled": True}})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["_picture_filename"], "CAN接线图.png")
        self.assertEqual(result[0]["image"].size, (24, 24))
        rotated = io.BytesIO()
        img = Image.new("RGB", (20, 30))
        exif = Image.Exif()
        exif[274] = 6
        img.save(rotated, format="JPEG", exif=exif)
        result = namespace["chunk"]("旋转照片.jpg", rotated.getvalue(), "tenant", "Chinese", parser_config={"multimodal": {"enabled": True}})
        self.assertEqual(result[0]["image"].size, (30, 20))
        with self.assertRaisesRegex(ValueError, "video"):
            namespace["chunk"]("a.mp4", b"video", "tenant", "Chinese", parser_config={"multimodal": {"enabled": True}})
        tree = ast.parse(source.read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == "OCR" for n in tree.body))

    def test_picture_filename_is_indexed_and_archived_without_poisoning_cache(self):
        from PIL import Image
        fake_nlp = types.ModuleType("rag.nlp")
        fake_nlp.tokenize = lambda chunk, text, *a, **kw: chunk.update(content_with_weight=text)
        calls = []
        def complete(*args):
            calls.append(1)
            return response("# 图片描述\nCAN 模块连接控制器。")
        with patch.dict("sys.modules", {"rag.nlp": fake_nlp}), patch.dict("os.environ", {"RAGFLOW_MULTIMODAL_ARCHIVE_DIR": self.temp.name}), patch.object(m.ScreenshotParser, "_complete", complete):
            for name in ["CAN接线图.png", "更名后的接线图.png"]:
                task = {"tenant_id": "tenant", "doc_id": "doc", "name": name, "id": "task"}
                chunk = {"image": Image.new("RGB", (24, 24)), "_picture_filename": name}
                result = m.parse_chunks([chunk], task, b"image", {}, self.model, lambda **kw: None)
                self.assertIn(name, result[0]["content_with_weight"])
                self.assertIn("CAN 模块", result[0]["content_with_weight"])
                self.assertNotIn("_picture_filename", result[0])
        self.assertEqual(len(calls), 1)
        manifests = [json.loads(p.read_text(encoding="utf-8")) for p in Path(self.temp.name).rglob("runs/*.json")]
        for manifest in manifests:
            self.assertIn(manifest["name"], manifest["chunks"][0]["indexed_markdown"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.model = {"llm_name": "qwen-test", "api_base": "http://localhost:8000/v1", "api_key": "SECRET", "llm_factory": "vLLM"}

    def complete(self, png, prompt):
        self.calls.append((png, prompt))
        return response()

    def parser(self, **options):
        return m.ScreenshotParser(self.temp.name, "tenant", self.model, options, self.complete)

    def test_chunk_order_and_count_do_not_change_identity(self):
        first, a = self.parser().parse(b"same image", {"chunk_index": 2, "chunk_count": 3})
        second, b = self.parser().parse(b"same image", {"chunk_index": 7, "chunk_count": 20})
        self.assertEqual(first, second)
        self.assertEqual(a["key"], b["key"])
        self.assertTrue(b["cache_hit"])
        self.assertEqual(len(self.calls), 1)

    def test_current_run_usage_is_counted_and_cache_hits_are_zero(self):
        _, first = self.parser().parse(b"usage-image", {})
        _, cached = self.parser().parse(b"usage-image", {})
        self.assertEqual(first["usage"]["total_tokens"], 12)
        self.assertEqual(cached["usage"]["total_tokens"], 0)

    def test_smart_mode_keeps_plain_text_and_visually_recovers_selected_chunks(self):
        from PIL import Image

        fake_nlp = types.ModuleType("rag.nlp")
        fake_nlp.tokenize = lambda chunk, text, *a, **kw: chunk.update(content_with_weight=text)
        answers = iter([
            response("TEXT"),
            response("MULTIMODAL"),
            response("# Recovered table\n\n| A |\n| --- |\n| 1 |"),
        ])
        chunks = [
            {"content_with_weight": "plain OCR", "image": Image.new("RGB", (20, 20), "white")},
            {"content_with_weight": "broken table OCR", "image": Image.new("RGB", (21, 20), "white")},
        ]
        task = {"tenant_id": "tenant", "doc_id": "doc", "name": "test.pdf", "id": "task", "language": "Chinese"}
        options = {"enabled": True, "mode": "smart", "model": "vision", "router_max_tokens": 64}
        with patch.dict("sys.modules", {"rag.nlp": fake_nlp}), patch.dict(
            "os.environ", {"RAGFLOW_MULTIMODAL_ARCHIVE_DIR": self.temp.name}
        ), patch.object(m.ScreenshotParser, "_complete", lambda *args: next(answers)):
            result = m.parse_chunks(chunks, task, b"pdf", options, self.model, lambda **kwargs: None)

        self.assertEqual(result[0]["content_with_weight"], "plain OCR")
        self.assertIn("Recovered table", result[1]["content_with_weight"])
        manifest = json.loads(next(Path(self.temp.name).rglob("runs/*.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["mode"], "smart")
        self.assertEqual(manifest["routed_chunk_count"], 2)
        self.assertEqual(manifest["multimodal_chunk_count"], 1)
        self.assertEqual(manifest["usage"]["total_tokens"], 36)
        self.assertTrue(manifest["chunks"][0]["kept_base_parse"])
        self.assertEqual(manifest["chunks"][1]["route"]["decision"], "MULTIMODAL")

    def test_changed_crop_prompt_model_revision_or_limit_invalidates(self):
        keys = [self.parser().parse(b"image", {})[1]["key"]]
        for options in [{"prompt": "new"}, {"model_revision": "v2"}, {"max_tokens": 16384}, {"enable_thinking": True}]:
            keys.append(self.parser(**options).parse(b"image", {})[1]["key"])
        keys.append(self.parser().parse(b"new crop", {})[1]["key"])
        self.assertEqual(len(set(keys)), 6)

    def test_force_preserves_previous_attempts_and_credentials_absent(self):
        self.parser().parse(b"image", {})
        self.parser(reuse=False).parse(b"image", {})
        self.assertEqual(len(list(Path(self.temp.name).rglob("result.md"))), 2)
        self.assertFalse(any("SECRET" in p.read_text(encoding="utf-8") for p in Path(self.temp.name).rglob("*.json")))

    def test_invalid_and_truncated_outputs_are_archived_not_cached(self):
        for raw in [response("| A | B |\n| --- | --- |\n| X |"), response("partial", "length")]:
            parser = self.parser()
            parser.completion = lambda *args: raw
            with self.assertRaises(ValueError):
                parser.parse(b"bad", {})
        self.assertEqual(len(list(Path(self.temp.name).rglob("response.json"))), 4)
        self.assertEqual(len(list(Path(self.temp.name).rglob("success.json"))), 0)

    def test_failed_refresh_preserves_previous_success(self):
        _, original = self.parser().parse(b"image", {})
        parser = self.parser(reuse=False)
        parser.completion = lambda *args: response("bad", "length")
        with self.assertRaises(ValueError):
            parser.parse(b"image", {})
        _, cached = self.parser().parse(b"image", {})
        self.assertEqual(original["attempt"], cached["attempt"])

    def test_api_failure_recorded_without_exception_secrets(self):
        parser = self.parser()
        def fail(*args):
            raise RuntimeError("SECRET")
        parser.completion = fail
        with self.assertRaises(RuntimeError):
            parser.parse(b"image", {})
        status = json.loads(next(Path(self.temp.name).rglob("status.json")).read_text())
        self.assertEqual(status["status"], "api_error")
        self.assertNotIn("SECRET", json.dumps(status))

    def test_tenant_isolation(self):
        self.parser().parse(b"image", {})
        other = m.ScreenshotParser(self.temp.name, "other", self.model, {}, self.complete)
        self.assertFalse(other.parse(b"image", {})[1]["cache_hit"])

    def test_markdown_validation_preserves_empty_cells_and_escaped_pipes(self):
        valid = "| A | B |\n| --- | --- |\n|| X \\| Y |"
        self.assertEqual(m.validate_markdown(valid), valid)
        for text in ["<table><tr><td>X</td></tr></table>", "", "| A | B |\n| C | D |"]:
            with self.assertRaises(ValueError):
                m.validate_markdown(text)

    def test_archive_export_import_can_reuse_without_api(self):
        self.parser().parse(b"image", {})
        bundle = Path(self.temp.name) / "export.zip"
        sync.export_archive(self.temp.name, bundle)
        with tempfile.TemporaryDirectory() as destination:
            self.assertGreater(sync.import_archive(destination, bundle), 0)
            self.assertEqual(sync.import_archive(destination, bundle), 0)
            parser = m.ScreenshotParser(destination, "tenant", self.model, {}, lambda *args: self.fail("Unexpected API call"))
            self.assertTrue(parser.parse(b"image", {})[1]["cache_hit"])

    def test_import_rejects_path_traversal_before_writing(self):
        bundle = Path(self.temp.name) / "bad.zip"
        with zipfile.ZipFile(bundle, "w") as stream:
            stream.writestr("../escaped.json", "bad")
            stream.writestr("bundle.json", json.dumps({"schema_version": 1, "sha256": {"../escaped.json": m._hash(b"bad")}}))
        with self.assertRaises(ValueError):
            sync.import_archive(Path(self.temp.name) / "destination", bundle)
        self.assertFalse((Path(self.temp.name) / "escaped.json").exists())

    def test_ingestion_replaces_ocr_retains_image_positions_and_records_runs(self):
        from PIL import Image
        image = Image.new("RGB", (20, 20), "white")
        task = {"tenant_id": "tenant", "doc_id": "doc", "name": "test.pdf", "id": "task", "language": "Chinese"}
        chunks = [
            {"content_with_weight": "old OCR", "image": image, "position_int": [[1, 0, 20, 0, 20]]},
            {"content_with_weight": "same table next row", "image": image, "position_int": [[1, 0, 20, 0, 20]]},
            {"content_with_weight": "same screenshot other page", "image": image, "position_int": [[2, 0, 20, 0, 20]]},
        ]
        def tokenize(chunk, text, *args, **kwargs):
            chunk.update(content_with_weight=text, content_ltks="new tokens", content_sm_ltks="new small tokens")
        fake_nlp = types.ModuleType("rag.nlp")
        fake_nlp.tokenize = tokenize
        with patch.dict("sys.modules", {"rag.nlp": fake_nlp}), patch.dict("os.environ", {"RAGFLOW_MULTIMODAL_ARCHIVE_DIR": self.temp.name}), patch.object(m.ScreenshotParser, "_complete", lambda *args: response()):
            result = m.parse_chunks(chunks, task, b"pdf", {}, self.model, lambda **kwargs: None)
        self.assertEqual(result[0]["content_with_weight"], response()["choices"][0]["message"]["content"])
        self.assertIs(result[0]["image"], image)
        self.assertEqual(result[0]["position_int"], [[1, 0, 20, 0, 20]])
        self.assertEqual(len(result), 2)
        self.assertNotEqual(result[0]["_multimodal_image_sha256"], result[1]["_multimodal_image_sha256"])
        manifest = json.loads(next(Path(self.temp.name).rglob("runs/*.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "ok")
        self.assertEqual(manifest["mode"], "full")
        self.assertEqual(manifest["usage"]["total_tokens"], 24)
        self.assertEqual(manifest["multimodal_chunk_count"], 2)
        self.assertEqual(manifest["result_chunk_count"], 2)
        self.assertTrue(manifest["chunks"][1]["duplicate_source"])
        self.assertEqual(manifest["chunks"][0]["positions"], result[0]["position_int"])

    def test_invalid_repair_can_succeed_without_losing_first_response(self):
        parser = self.parser()
        answers = iter([response("partial", "length"), response()])
        parser.completion = lambda *args: next(answers)
        parser.parse(b"image", {})
        self.assertEqual(len(list(Path(self.temp.name).rglob("response.json"))), 2)
        statuses = [json.loads(p.read_text(encoding="utf-8"))["status"] for p in Path(self.temp.name).rglob("status.json")]
        self.assertCountEqual(statuses, ["invalid", "ok"])

    def test_document_override_and_disabled_mode(self):
        task = {"kb_parser_config": {"ext": {"multimodal": {"enabled": True, "model": "kb-model"}}}, "parser_config": {"multimodal": {"enabled": False}}}
        config = {"children_delimiter": "\\n"}
        self.assertFalse(m.configure_multimodal(task, config)["enabled"])
        self.assertNotIn("multimodal", config)
        task["parser_config"] = {"ext": {"multimodal": {"max_tokens": 16000}}}
        self.assertEqual(m.configure_multimodal(task, config)["model"], "kb-model")
        self.assertEqual(config["children_delimiter"], "")
        self.assertEqual(task["parser_config"]["multimodal"]["max_tokens"], 16000)

    def test_legacy_enabled_maps_to_full_and_explicit_smart_is_preserved(self):
        legacy_task = {"parser_config": {"multimodal": {"enabled": True, "model": "vision"}}}
        self.assertEqual(m.configure_multimodal(legacy_task, {})["mode"], "full")
        smart_task = {"parser_config": {"multimodal": {"enabled": True, "mode": "smart", "model": "vision"}}}
        self.assertEqual(m.configure_multimodal(smart_task, {})["mode"], "smart")

    def test_parent_child_is_rejected_before_call(self):
        task = {"parser_config": {"multimodal": {"enabled": True, "model": "model"}}}
        with self.assertRaises(ValueError):
            m.configure_multimodal(task, {"enable_children": True})

    def test_default_executor_calls_multimodal_after_chunking(self):
        # Load the real orchestration function without database/OCR service dependencies.
        import logging
        from functools import partial
        from timeit import default_timer
        source = Path(__file__).resolve().parents[2] / "rag/svr/task_executor_refactor/chunk_builder.py"
        func = next(n for n in ast.parse(source.read_text(encoding="utf-8")).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_chunking")
        events = []
        task = {"parser_config": {"multimodal": {"enabled": True, "model": "vision"}}}
        async def thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)
        def chunk(*args, **kwargs):
            events.append("chunk")
            self.assertTrue(kwargs["parser_config"]["multimodal"]["enabled"])
            return [{"content_with_weight": "OCR"}]
        def enhance(chunks, *args):
            events.append("multimodal")
            return [{"content_with_weight": "# Markdown"}]
        ctx = types.SimpleNamespace(raw_task=task, chunk_limiter=asyncio.Semaphore(1), name="a.pdf", from_page=0, to_page=1, language="Chinese", progress_cb=lambda *a, **k: None, kb_id="kb", tenant_id="tenant", has_canceled_func=lambda _: False, id="id", location="a", recording_context=types.SimpleNamespace(record=lambda *a: None))
        namespace = {"Dict": dict, "List": list, "TaskContext": object, "timer": default_timer, "thread_pool_exec": thread, "merge_table_parser_config_from_kb": lambda t: dict(t["parser_config"]), "logging": logging, "partial": partial, "TaskCanceledException": type("TaskCanceledException", (Exception,), {})}
        exec(compile(ast.Module(body=[func], type_ignores=[]), str(source), "exec"), namespace)
        with patch.dict("sys.modules", {"rag.svr.chunk_multimodal": m}), patch.object(m, "parse_with_config", enhance):
            result = asyncio.run(namespace["run_chunking"](types.SimpleNamespace(chunk=chunk), b"pdf", ctx))
        self.assertEqual(events, ["chunk", "multimodal"])
        self.assertEqual(result[0]["content_with_weight"], "# Markdown")

    def test_openai_request_contains_screenshot_and_qwen_thinking_options(self):
        captured = []
        class Client:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))
            def create(self, **kwargs):
                captured.append(kwargs)
                return types.SimpleNamespace(model_dump=lambda **kwargs: response())
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        with patch.dict("sys.modules", {"openai": types.SimpleNamespace(OpenAI=Client)}):
            self.parser()._complete(b"png", "prompt")
        request = captured[0]
        self.assertEqual(request["extra_body"], {"chat_template_kwargs": {"enable_thinking": False}})
        self.assertEqual(request["messages"][0]["content"][1]["image_url"]["url"], "data:image/png;base64,cG5n")
        self.assertEqual(request["max_tokens"], 8192)

    def test_openai_request_accepts_multiple_labeled_source_pages(self):
        from rag.svr.multimodal_source_renderer import RenderedVisual

        captured = []

        class Client:
            def __init__(self, **kwargs):
                self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

            def create(self, **kwargs):
                captured.append(kwargs)
                return types.SimpleNamespace(model_dump=lambda **kwargs: response())

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        visuals = [
            RenderedVisual(b"page-one", {"source_type": "pdf", "page": 1}, "Page 1"),
            RenderedVisual(b"page-two", {"source_type": "pdf", "page": 2}, "Page 2"),
        ]
        with patch.dict("sys.modules", {"openai": types.SimpleNamespace(OpenAI=Client)}):
            self.parser()._complete(visuals, "prompt")

        content = captured[0]["messages"][0]["content"]
        self.assertEqual([item["text"] for item in content if item["type"] == "text"], ["prompt", "Page 1", "Page 2"])
        self.assertEqual(len([item for item in content if item["type"] == "image_url"]), 2)

    def test_missing_chunk_image_uses_source_renderer_and_retains_source_fields(self):
        fake_nlp = types.ModuleType("rag.nlp")
        fake_nlp.tokenize = lambda chunk, text, *a, **kw: chunk.update(
            content_with_weight=text,
            content_ltks="new tokens",
            content_sm_ltks="new small tokens",
        )
        source_fields = {
            "doc_id": "doc-1",
            "dataset_id": "kb-1",
            "location": "bucket/source.txt",
            "sha256": "source-sha",
            "position_int": [[7, 0, 0, 0, 0]],
            "page_num_int": [7],
        }
        chunk = {**source_fields, "content_with_weight": "original text"}
        task = {
            "tenant_id": "tenant",
            "doc_id": "doc-1",
            "name": "source.txt",
            "id": "task",
            "language": "Chinese",
        }

        with patch.dict("sys.modules", {"rag.nlp": fake_nlp}), patch.dict(
            "os.environ", {"RAGFLOW_MULTIMODAL_ARCHIVE_DIR": self.temp.name}
        ), patch.object(m.ScreenshotParser, "_complete", lambda *args: response()):
            result = m.parse_chunks([chunk], task, b"original text", {}, self.model, lambda **kwargs: None)

        for key, value in source_fields.items():
            self.assertEqual(result[0][key], value)
        manifest = json.loads(next(Path(self.temp.name).rglob("runs/*.json")).read_text(encoding="utf-8"))
        locator = manifest["chunks"][0]["visuals"][0]["locator"]
        self.assertEqual(locator["location"], source_fields["location"])
        self.assertEqual(locator["sha256"], source_fields["sha256"])
        self.assertEqual(locator["positions"], source_fields["position_int"])

    def test_archive_locator_inherits_original_identity_from_task(self):
        fake_nlp = types.ModuleType("rag.nlp")
        fake_nlp.tokenize = lambda chunk, text, *a, **kw: chunk.update(content_with_weight=text)
        task = {
            "tenant_id": "tenant",
            "kb_id": "dataset-from-task",
            "doc_id": "document-from-task",
            "location": "minio/path/original.md",
            "name": "original.md",
            "id": "task",
            "language": "Chinese",
        }
        with patch.dict("sys.modules", {"rag.nlp": fake_nlp}), patch.dict(
            "os.environ", {"RAGFLOW_MULTIMODAL_ARCHIVE_DIR": self.temp.name}
        ), patch.object(m.ScreenshotParser, "_complete", lambda *args: response()):
            m.parse_chunks([{"content_with_weight": "source"}], task, b"source bytes", {}, self.model, lambda **kwargs: None)

        manifest = json.loads(next(Path(self.temp.name).rglob("runs/*.json")).read_text(encoding="utf-8"))
        locator = manifest["chunks"][0]["visuals"][0]["locator"]
        self.assertEqual(locator["doc_id"], task["doc_id"])
        self.assertEqual(locator["dataset_id"], task["kb_id"])
        self.assertEqual(locator["location"], task["location"])
        self.assertEqual(locator["sha256"], manifest["file_sha256"])

    def test_shared_renderer_accepts_chunks_from_every_builtin_method(self):
        parser_ids = [
            "naive",
            "qa",
            "resume",
            "manual",
            "table",
            "paper",
            "book",
            "laws",
            "presentation",
            "picture",
            "one",
            "audio",
            "email",
            "tag",
            "knowledge_graph",
        ]
        chunks = [
            {"parser_id_kwd": parser_id, "content_with_weight": f"source from {parser_id}"}
            for parser_id in parser_ids
        ]
        fake_nlp = types.ModuleType("rag.nlp")
        fake_nlp.tokenize = lambda chunk, text, *a, **kw: chunk.update(content_with_weight=text)
        task = {
            "tenant_id": "tenant",
            "kb_id": "kb",
            "doc_id": "doc",
            "location": "source.txt",
            "name": "source.txt",
            "id": "task",
            "language": "Chinese",
        }

        with patch.dict("sys.modules", {"rag.nlp": fake_nlp}), patch.dict(
            "os.environ", {"RAGFLOW_MULTIMODAL_ARCHIVE_DIR": self.temp.name}
        ), patch.object(m.ScreenshotParser, "_complete", lambda *args: response()):
            result = m.parse_chunks(chunks, task, b"source", {}, self.model, lambda **kwargs: None)

        self.assertEqual([chunk["parser_id_kwd"] for chunk in result], parser_ids)


if __name__ == "__main__":
    unittest.main()
