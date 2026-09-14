"""Dependency-free contract tests for scoped, bounded unseen-chunk search."""

import copy
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_search():
    common = types.ModuleType("common")
    common.settings = types.SimpleNamespace()
    path = Path(__file__).resolve().parents[2] / "rag/advanced_rag/harness/tools/search.py"
    spec = importlib.util.spec_from_file_location("unseen_search_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"common": common}):
        spec.loader.exec_module(module)
    return module


async def run_sync(fn, *args):
    return fn(*args)


class Retriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    async def retrieval(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        page, size = args[4:6]
        start = (page - 1) * size
        return {"chunks": copy.deepcopy(self.chunks[start : start + size]), "doc_aggs": [], "total": len(self.chunks)}

    def retrieval_by_children(self, chunks, tenants):
        for chunk in chunks:
            chunk["chunk_id"] = chunk.pop("mom_id", chunk["chunk_id"])
        return chunks


def chunk(cid, **extra):
    return {"chunk_id": cid, "doc_id": "doc", "kb_id": "kb", "content_with_weight": "relevant text", **extra}


class UnseenSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.search = load_search()
        self.retriever = Retriever([])
        self.search.settings.retriever = self.retriever
        self.tools = types.SimpleNamespace(
            kb_ids=["kb"],
            tenant_ids=["tenant"],
            embed_mdl=None,
            search_cache={},
            _filter_known_doc_ids=lambda ids: set(ids) & {"doc"},
            _resolve_doc_tenant=lambda doc_id: ("kb", "tenant"),
        )
        self.misc_patch = patch.dict(sys.modules, {"common.misc_utils": types.SimpleNamespace(thread_pool_exec=run_sync)})
        self.misc_patch.start()
        self.addCleanup(self.misc_patch.stop)

    async def test_excludes_normalized_parent_and_refills_across_pages(self):
        self.retriever.chunks = [chunk(str(i), mom_id="seen") for i in range(30)] + [chunk("fresh1"), chunk("fresh2")]
        result = await self.search.hybrid_search(self.tools, "q", top_n=2, exclude_ids=["seen"])
        self.assertEqual([c["chunk_id"] for c in result["chunks"]], ["fresh1", "fresh2"])
        self.assertEqual(len(self.retriever.calls), 2)
        self.assertFalse(result["search_metadata"]["budget_exhausted"])
        self.assertTrue(all("exclude_ids" not in kwargs for _, kwargs in self.retriever.calls))

    async def test_exclusion_cache_is_distinct_and_normal_cache_preserved(self):
        self.retriever.chunks = [chunk("seen"), chunk("fresh")]
        normal = await self.search.hybrid_search(self.tools, "q", top_n=1)
        self.assertIs(normal, await self.search.hybrid_search(self.tools, "q", top_n=1, exclude_ids=[]))
        unseen = await self.search.hybrid_search(self.tools, "q", top_n=1, exclude_ids=["seen"])
        self.assertEqual(unseen["chunks"][0]["chunk_id"], "fresh")
        self.assertEqual(normal["chunks"][0]["chunk_id"], "seen")
        self.assertIs(unseen, await self.search.hybrid_search(self.tools, "q", top_n=1, exclude_ids=["seen"]))
        self.assertEqual(len(self.retriever.calls), 2)

    async def test_budget_exhaustion_is_explicit(self):
        self.retriever.chunks = [chunk(str(i), mom_id="seen") for i in range(1000)]
        result = await self.search.hybrid_search(self.tools, "q", top_n=3, exclude_ids=["seen"])
        self.assertEqual(result["chunks"], [])
        metadata = result["search_metadata"]
        self.assertTrue(metadata["budget_exhausted"])
        self.assertEqual(metadata["retrieval_calls"], 4)
        self.assertEqual(metadata["candidates_examined"], metadata["candidate_budget"])
        self.assertLessEqual(metadata["candidate_budget"], 400)

    async def test_short_rerank_page_does_not_mean_backend_exhausted(self):
        async def retrieval(*args, **kwargs):
            self.retriever.calls.append((args, kwargs))
            page = args[4]
            rows = [chunk("seen")] if page == 1 else [chunk("fresh")] if page == 4 else []
            return {"chunks": rows, "doc_aggs": [], "total": len(rows)}

        self.retriever.retrieval = retrieval
        result = await self.search.hybrid_search(self.tools, "q", top_n=1, exclude_ids=["seen"])
        self.assertEqual([c["chunk_id"] for c in result["chunks"]], ["fresh"])
        self.assertEqual(len(self.retriever.calls), 4)

    async def test_source_documents_follow_final_cross_page_evidence(self):
        async def retrieval(*args, **kwargs):
            if args[4] == 1:
                return {"chunks": [chunk("seen", doc_id="old")], "doc_aggs": [{"doc_id": "old", "doc_name": "old.pdf"}]}
            return {"chunks": [chunk("fresh", doc_id="new", docnm_kwd="new.pdf")], "doc_aggs": [{"doc_id": "new", "doc_name": "new.pdf"}]}

        self.retriever.retrieval = retrieval
        result = await self.search.hybrid_search(self.tools, "q", top_n=1, exclude_ids=["seen"])
        self.assertEqual(result["doc_aggs"], [{"doc_id": "new", "doc_name": "new.pdf", "count": 1}])

    async def test_deduplicates_and_bounds_returned_chunks(self):
        self.retriever.chunks = [chunk("a"), chunk("a"), chunk("b"), chunk("c")]
        result = await self.search.hybrid_search(self.tools, "q", top_n=2, exclude_ids=["seen"])
        self.assertEqual([c["chunk_id"] for c in result["chunks"]], ["a", "b"])

    async def test_large_limit_cannot_bypass_candidate_budget(self):
        self.retriever.chunks = [chunk(str(i)) for i in range(600)]
        result = await self.search.hybrid_search(self.tools, "q", top_n=500, exclude_ids=["seen"])
        self.assertEqual(len(result["chunks"]), 400)
        self.assertTrue(result["search_metadata"]["budget_exhausted"])
        self.assertEqual([args[5] for args, _ in self.retriever.calls], [100] * 4)

    async def test_keyword_narrowing_does_not_prevent_refill(self):
        self.retriever.chunks = [chunk(str(i)) for i in range(24)] + [chunk("fresh", content_with_weight="alpha evidence.")]
        result = await self.search.hybrid_search(self.tools, "q", top_n=1, keywords="alpha,beta,gamma", exclude_ids=["seen"])
        self.assertEqual([c["chunk_id"] for c in result["chunks"]], ["fresh"])
        self.assertEqual(len(self.retriever.calls), 2)

    async def test_invalid_or_empty_scope_never_retrieves_globally(self):
        for scope in ({"kb_ids": ["other"]}, {"kb_ids": ["kb", "other"]}, {"kb_ids": []}, {"doc_scope": ["other"]}, {"doc_scope": ["doc", "other"]}, {"doc_scope": []}):
            with self.subTest(scope=scope):
                result = await self.search.hybrid_search(self.tools, "q", **scope)
                self.assertEqual(result["chunks"], [])
        self.assertEqual(self.retriever.calls, [])

    async def test_valid_scope_reaches_retrieval(self):
        self.retriever.chunks = [chunk("a")]
        result = await self.search.hybrid_search(self.tools, "q", kb_ids=["kb"], doc_scope=["doc"], exclude_ids=["seen"])
        self.assertEqual(len(result["chunks"]), 1)
        self.assertEqual(self.retriever.calls[0][0][3], ["kb"])
        self.assertEqual(self.retriever.calls[0][1]["doc_ids"], ["doc"])

    async def test_document_outside_explicit_kb_subset_is_rejected(self):
        self.tools.kb_ids = ["kb", "second"]
        self.tools._resolve_doc_tenant = lambda doc_id: ("second", "tenant")
        result = await self.search.hybrid_search(self.tools, "q", kb_ids=["kb"], doc_scope=["doc"])
        self.assertEqual(result["chunks"], [])
        self.assertEqual(self.retriever.calls, [])

    async def test_zero_limit_does_not_retrieve(self):
        result = await self.search.hybrid_search(self.tools, "q", top_n=0, exclude_ids=["seen"])
        self.assertEqual(result["chunks"], [])
        self.assertEqual(self.retriever.calls, [])


if __name__ == "__main__":
    unittest.main()
