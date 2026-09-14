"""Exercise the actual RAGTools iterator with a paginated storage boundary."""

import ast
import asyncio
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


async def thread_call(fn, *args, **kwargs):
    return fn(*args, **kwargs)


class IteratorTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.rows = [{"id": str(i), "doc_id": "doc", "content_with_weight": f"MLLM {i}", "position_int": [[i + 1, 0, 1, 0, 1]], "img_id": "image"} for i in range(130)]

        def chunk_list(doc, tenant, kbs, **kwargs):
            self.calls.append((doc, tenant, kbs, kwargs))
            return deepcopy(self.rows[kwargs["offset"] : kwargs["max_count"]])

        source = ast.parse((ROOT / "rag/advanced_rag/agentic_rag.py").read_text(encoding="utf-8"))
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "RAGTools")
        method = next((n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "iter_document_chunks"), None)
        self.assertIsNotNone(method, "RAGTools must implement an indexed document iterator")
        namespace = {"thread_pool_exec": thread_call, "settings": SimpleNamespace(retriever=SimpleNamespace(chunk_list=chunk_list))}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "RAGTools.iter_document_chunks", "exec"), namespace)  # noqa: S102 -- execute the repository method under test
        self.fn = namespace["iter_document_chunks"]
        self.tools = SimpleNamespace(kb_ids=["kb"], tenant_ids=["tenant"], _resolve_doc_tenant=lambda doc: ("kb", "tenant") if doc == "doc" else None)

    def collect(self, doc="doc"):
        async def run():
            return [c async for c in self.fn(self.tools, doc)]

        return asyncio.run(run())

    def test_reads_after_first_page_and_preserves_vlm_evidence(self):
        chunks = self.collect()
        self.assertEqual(len(chunks), 130)
        self.assertEqual(chunks[-1]["chunk_id"], "129")
        self.assertEqual(chunks[-1]["content_with_weight"], "MLLM 129")
        self.assertEqual(chunks[-1]["image_id"], "image")
        self.assertEqual(chunks[-1]["positions"], [[130, 0, 1, 0, 1]])
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(c[3]["sort_by_position"] for c in self.calls))
        self.assertTrue(all(c[2] == ["kb"] for c in self.calls))

    def test_unknown_document_never_reaches_storage(self):
        with self.assertRaises(ValueError):
            self.collect("outside")
        self.assertFalse(self.calls)

    def test_disabled_and_compiled_chunks_not_visible(self):
        self.rows[0]["available_int"] = 0
        self.rows[1]["compile_kwd"] = "summary"
        chunks = self.collect()
        self.assertEqual(chunks[0]["chunk_id"], "2")
        self.assertEqual(chunks[0]["chunk_order"], 0)

    def test_wrong_document_returned_by_store_rejected(self):
        self.rows[0]["doc_id"] = "outside"
        with self.assertRaises(ValueError):
            self.collect()

    def test_missing_position_does_not_invent_reading_order(self):
        self.rows[0].pop("position_int")
        with self.assertRaises(ValueError):
            self.collect()

    def test_repeated_page_does_not_silently_loop(self):
        self.rows[128]["id"] = "0"
        with self.assertRaises(ValueError):
            self.collect()

    def test_real_index_list_kb_id_is_accepted(self):
        self.rows[0]["kb_id"] = ["kb"]
        self.assertEqual(self.collect()[0]["chunk_id"], "0")

    def test_geometry_orders_top_before_left_offset(self):
        self.rows = [
            {"id": "lower", "doc_id": "doc", "position_int": [[1, 0, 200, 200, 250]]},
            {"id": "upper", "doc_id": "doc", "position_int": [[1, 50, 200, 100, 150]]},
        ]
        self.assertEqual([c["chunk_id"] for c in self.collect()], ["upper", "lower"])

    def test_raptor_summary_is_not_a_source_chunk(self):
        self.rows[0]["raptor_kwd"] = "raptor"
        self.rows[0].pop("position_int")
        self.assertEqual(self.collect()[0]["chunk_order"], 0)
        self.assertEqual(self.collect()[0]["chunk_id"], "1")


if __name__ == "__main__":
    unittest.main()
