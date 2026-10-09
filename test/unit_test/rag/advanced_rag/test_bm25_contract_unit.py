"""Keyword search must keep explicit authorization and empty scopes."""

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


def search_function(calls):
    source = ast.parse((ROOT / "rag/advanced_rag/harness/tools/search.py").read_text(encoding="utf-8"))
    fn = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "bm25_search")

    async def retrieval(*args, **kwargs):
        calls.append((args, kwargs))
        return {"chunks": [], "doc_aggs": []}

    ns = {"_LOG": logging.getLogger(__name__), "_resolve_top_n": lambda tools, n: n or 12,
          "_resolve_top_k": lambda tools: 1024, "_resolve_rerank_candidates": lambda tools, n: max(64, n),
          "settings": SimpleNamespace(retriever=SimpleNamespace(retrieval=retrieval)),
          "_normalize": lambda result, tenants: result, "_narrow_or_keep": lambda chunks, *args: chunks}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "actual-bm25", "exec"), ns)  # noqa: S102 - trusted repository function
    return ns["bm25_search"]


@pytest.mark.parametrize("kwargs", [{"doc_scope": []}, {"kb_ids": []}, {"kb_ids": ["secret"]}])
def test_explicit_empty_or_unauthorized_scope_never_runs_retrieval(kwargs):
    calls = []
    tools = SimpleNamespace(kb_ids=["allowed"], tenant_ids=["tenant"])
    result = asyncio.run(search_function(calls)(tools, "CAN", **kwargs))
    assert calls == []
    assert result["chunks"] == []


def test_session_scope_intersection_cannot_widen_to_whole_corpus():
    calls = []
    tools = SimpleNamespace(kb_ids=["allowed"], tenant_ids=["tenant"], scoped_doc_ids=lambda ids: [])
    assert asyncio.run(search_function(calls)(tools, "CAN", doc_scope=["outside"]))["chunks"] == []
    assert calls == []


def test_keyword_contract_preserves_no_embedding_no_dense_fallback_and_compile_exclusion():
    calls = []
    tools = SimpleNamespace(kb_ids=["allowed"], tenant_ids=["tenant"])
    asyncio.run(search_function(calls)(tools, "CAN", doc_scope=["doc"]))
    args, kwargs = calls[0]
    assert args[1] is None
    assert args[3] == ["allowed"]
    assert kwargs["vector_similarity_weight"] == 0
    assert kwargs["allow_dense_fallback"] is False
    assert kwargs["must_not"] == {"exists": "compile_kwd"}
    assert kwargs["doc_ids"] == ["doc"]
