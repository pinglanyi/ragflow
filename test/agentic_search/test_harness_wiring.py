"""Run harness dispatch/formatting with real modules and no service bootstrap."""

import ast
import asyncio
import json
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "rag/advanced_rag/harness"


def load(path, namespace, names=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and (n.module or "").startswith("rag."))]
    if names:
        tree.body = [n for n in tree.body if getattr(n, "name", None) in names]
    exec(compile(tree, str(path), "exec"), namespace)  # noqa: S102 -- load repository code without service bootstrap


class Result:
    def __init__(self, chunks, metadata, error=None):
        self.chunks, self.metadata, self.error = chunks, metadata, error


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.ns = {"ToolResult": Result, "OrchestratorContext": object, "ExecutionStrategy": lambda **kw: SimpleNamespace(**kw)}
        load(HARNESS / "tools/registry.py", self.ns)
        load(HARNESS / "tools/inspector.py", self.ns)
        for name in ("hybrid_search", "vector_search", "bm25_search", "web_search", "structured_query", "catalog_navigate", "dataset_navigate", "mindmap_navigate", "graph_explore", "wiki_query"):
            self.ns[name] = lambda: None
        load(HARNESS / "tools/__init__.py", self.ns)
        load(HARNESS / "tools/gating.py", self.ns)
        load(HARNESS / "config.py", self.ns)
        load(HARNESS / "pipeline.py", self.ns)
        self.ns.update(json=json, _LOG=logging.getLogger(__name__))
        load(HARNESS / "agent.py", self.ns, {"_fmt_tool_result", "execute_with_fallback"})

    def test_all_advertised_names_dispatch_and_optional_defaults(self):
        registry = self.ns["TOOL_REGISTRY"]
        for name, entry in registry.items():
            self.assertEqual(name, entry["function_schema"]["function"]["name"])
        params = registry["inspector_read_document"]["function_schema"]["function"]["parameters"]
        self.assertEqual(params["required"], ["doc_id"])
        params = registry["hybrid_search"]["function_schema"]["function"]["parameters"]
        self.assertIn("exclude_ids", params["properties"])
        self.assertNotIn("exclude_ids", registry["bm25_search"]["function_schema"]["function"]["parameters"]["properties"])

    def test_navigation_reachable_in_both_agent_modes(self):
        context = SimpleNamespace(has_any_chunks=lambda: True, last_entity="entity")
        for mode in ("high", "ultra"):
            available = self.ns["THINKING_MODES"][mode].available_tools
            defs = self.ns["get_gated_tools"]("explore", available, {"kb": {"knowledge_graph"}}, context)
            names = {d["function"]["name"] for d in defs}
            self.assertTrue({"inspector_read_document", "inspector_request_adjacent", "inspector_grep_within"} <= names)

    def test_empty_local_read_and_scoped_search_do_not_fallback(self):
        calls = []

        async def execute(name, **kw):
            calls.append(name)
            return Result([], {"next_start": 10})

        for name, kwargs in (("inspector_read_document", {"doc_id": "doc"}), ("hybrid_search", {"query": "q", "doc_scope": []})):
            calls.clear()
            asyncio.run(self.ns["execute_with_fallback"](SimpleNamespace(execute=execute), name, "explore", **kwargs))
            self.assertEqual(calls, [name])

    def test_real_dispatch_merges_unseen_mllm_citation_and_metadata(self):
        async def iterator(doc):
            yield {"chunk_id": "new", "doc_id": doc, "content_with_weight": "|MLLM|表格|", "positions": [[1, 2, 3, 4, 5]], "image_id": "image", "chunk_order": 0}

        tools = SimpleNamespace(kbinfos={"chunks": [], "doc_aggs": []}, iter_document_chunks=iterator)
        pipeline = self.ns["Pipeline"](tools)
        result = asyncio.run(pipeline.execute("inspector_read_document", doc_id="doc", count=1))
        self.assertIsNone(result.error)
        self.assertEqual(result.metadata["next_start"], 1)
        self.assertEqual(tools.kbinfos["chunks"][0]["image_id"], "image")
        self.assertEqual(tools.kbinfos["chunks"][0]["positions"], [[1, 2, 3, 4, 5]])
        output = self.ns["_fmt_tool_result"](result)
        self.assertIn('"chunk_id": "new"', output)
        self.assertIn('"doc_id": "doc"', output)
        self.assertIn("|MLLM|表格|", output)

    def test_returned_errors_are_not_success_or_citations(self):
        async def invalid(tools):
            return {"chunks": [{"chunk_id": "leak"}], "error": "scope denied", "search_metadata": {"budget_exhausted": True}}

        self.ns["TOOL_REGISTRY"]["invalid"] = {"fn": invalid}
        tools = SimpleNamespace(kbinfos={"chunks": []})
        pipeline = self.ns["Pipeline"](tools)
        result = asyncio.run(pipeline.execute("invalid"))
        self.assertEqual(result.error, "scope denied")
        self.assertTrue(result.metadata["search_metadata"]["budget_exhausted"])
        self.assertFalse(pipeline.trace[-1]["success"])
        self.assertFalse(tools.kbinfos["chunks"])

    def test_formatter_no_longer_hides_fourth_passage_or_long_table(self):
        chunks = [{"chunk_id": str(i), "doc_id": "doc", "content_with_weight": "A" * 310 + "TABLE_END"} for i in range(4)]
        output = self.ns["_fmt_tool_result"](Result(chunks, {}))
        self.assertEqual(output.count("TABLE_END"), 4)
        self.assertIn('"chunk_id": "3"', output)

    def test_full_source_reread_upgrades_existing_citation_in_place(self):
        async def iterator(doc):
            yield {"chunk_id": "same", "doc_id": doc, "content_with_weight": "Full MLLM table", "chunk_order": 0}

        existing = {"chunk_id": "same", "content_with_weight": "narrowed"}
        tools = SimpleNamespace(kbinfos={"chunks": [{"chunk_id": "earlier"}, existing]}, iter_document_chunks=iterator)
        pipeline = self.ns["Pipeline"](tools)
        result = asyncio.run(pipeline.execute("inspector_read_document", doc_id="doc"))
        self.assertEqual(len(tools.kbinfos["chunks"]), 2)
        self.assertEqual(existing["content_with_weight"], "Full MLLM table")
        self.assertEqual(result.chunks[0]["evidence_index"], 1)

    def test_context_anchor_and_all_source_ids_remain_visible(self):
        chunks = [{"chunk_id": str(i), "content_with_weight": "X" * 2000} for i in range(41)]
        output = self.ns["_fmt_tool_result"](Result(chunks, {}))
        self.assertIn('"chunk_id": "20"', output)
        self.assertIn('"chunk_id": "40"', output)


if __name__ == "__main__":
    unittest.main()
