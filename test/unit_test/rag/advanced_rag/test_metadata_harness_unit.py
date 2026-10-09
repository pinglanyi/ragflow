"""Exercise the real agent metadata dispatch without loading provider runtimes."""

import ast
import asyncio
import json
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def isolate_provider_runtime(monkeypatch):
    for name, attrs in {
        "api.db.services.doc_metadata_service": {"DocMetadataService": SimpleNamespace()},
        "common.misc_utils": {"thread_pool_exec": None},
        "common.metadata_utils": {"meta_filter": None},
        "rag.advanced_rag.harness.tools.search": {"hybrid_search": None, "grep_search": None},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)


def harness():
    source = ast.parse((ROOT / "rag/advanced_rag/harness/action_session.py").read_text(encoding="utf-8"))
    nodes = [node for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in ("_exec_metadata_search", "_arg_query_list")]
    ns = {"ToolOutcome": lambda **kwargs: SimpleNamespace(**kwargs), "_kb_ids": lambda tools: tools.kb_ids,
          "_LOG": logging.getLogger(__name__), "OK": "ok", "MISS": "miss", "ERROR": "error"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "actual-harness", "exec"), ns)  # noqa: S102 - trusted repository functions
    return ns


def test_agent_metadata_only_returns_handles_and_honors_scope(monkeypatch):
    calls = []

    async def select(kbs, filters, logic="and", **kwargs):
        calls.append((kbs, kwargs))
        return {"doc_ids": ["d"], "documents": [{"doc_id": "d", "metadata": {"year": "2026"}}], "reason": "matched"}

    module = ModuleType("rag.advanced_rag.harness.tools.metadata")
    module.select_metadata_documents = select
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ns = harness()
    result = asyncio.run(ns["_exec_metadata_search"](SimpleNamespace(kb_ids=["kb"], doc_scope=["d"]),
        {"filters": [{"key": "year", "op": "=", "value": "2026"}]}))
    assert result.status == "ok"
    assert result.payload[0]["doc_ids"] == ["d"]
    assert calls == [(["kb"], {"doc_scope": ["d"]})]
    assert not getattr(result, "evidence_ids", [])


def test_existing_query_path_keeps_its_original_retrieval(monkeypatch):
    ns = harness()
    expected = object()

    async def original(tools, args):
        assert args["query"] == ["CAN 接线"]
        return expected

    ns["_exec_metadata_retrieval"] = original
    assert asyncio.run(ns["_exec_metadata_search"](SimpleNamespace(), {"query": ["CAN 接线"], "filters": []})) is expected


@pytest.mark.parametrize("failure,reason", [(ValueError("bad filter"), "bad_args"), (RuntimeError("offline"), "infra")])
def test_metadata_dispatch_does_not_report_backend_errors_as_misses(monkeypatch, failure, reason):
    async def fail(*args, **kwargs):
        raise failure

    module = ModuleType("rag.advanced_rag.harness.tools.metadata")
    module.select_metadata_documents = fail
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ns = harness()
    result = asyncio.run(ns["_exec_metadata_search"](SimpleNamespace(kb_ids=["kb"]), {"filters": []}))
    assert result.status == "error"
    assert result.reason == reason


def test_model_schema_allows_real_metadata_fields_and_optional_query():
    source = ast.parse((ROOT / "rag/advanced_rag/harness/action_session.py").read_text(encoding="utf-8"))
    node = next(node for node in source.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_METADATA_SEARCH_TOOL_SPEC" for t in node.targets))
    schema = ast.literal_eval(node.value)["function"]
    params = schema["parameters"]
    assert params["required"] == ["filters"]
    assert "enum" not in params["properties"]["filters"]["items"]["properties"]["key"]
    assert params["properties"]["filters"]["maxItems"] == 10
    assert len(schema["description"]) <= 1200
    for anchor in ("WHEN TO CALL", "DO NOT CALL", "ARGUMENTS", "OUTPUT", "IF IT FAILS"):
        assert anchor in schema["description"]


def test_retrieve_schema_accepts_document_handles():
    source = ast.parse((ROOT / "rag/advanced_rag/harness/action_session.py").read_text(encoding="utf-8"))
    node = next(node for node in source.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_RETRIEVE_TOOL_SPEC" for t in node.targets))
    schema = ast.literal_eval(node.value)["function"]
    assert schema["parameters"]["properties"]["doc_scope"]["items"]["type"] == "string"
    assert "NOT a declared" not in schema["description"]


def test_metadata_budget_preserves_valid_json_and_matching_handles():
    source = ast.parse((ROOT / "rag/advanced_rag/harness/action_session.py").read_text(encoding="utf-8"))
    node = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "_metadata_tool_payload")
    ns = {"json": json}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "metadata-budget", "exec"), ns)  # noqa: S102 - trusted repository function
    result = {"kind": "metadata_search", "doc_ids": ["a", "b"], "documents": [
        {"doc_id": "a", "metadata": {"text": "测" * 10000}}, {"doc_id": "b", "metadata": {}}], "reason": "matched"}
    payload = ns["_metadata_tool_payload"]([result], 800)
    parsed = json.loads(payload)["passages"][0]
    assert len(payload) <= 800
    assert parsed["truncated"] is True
    assert parsed["doc_ids"] == [doc["doc_id"] for doc in parsed["documents"]]
    assert result["doc_ids"] == ["a", "b"]  # cached outcome remains intact


def test_explicit_empty_retrieve_scope_never_searches_entire_corpus():
    source = ast.parse((ROOT / "rag/advanced_rag/harness/action_session.py").read_text(encoding="utf-8"))
    nodes = [node for node in source.body if isinstance(node, ast.AsyncFunctionDef) and node.name in ("execute_tool", "_exec_retrieve")]
    async def forbidden(*args, **kwargs):
        pytest.fail("An explicitly empty scope must not run corpus search")

    ns = {"_run_search": forbidden, "_TOOL_MAP": {"retrieve": True}, "ToolOutcome": lambda **kwargs: SimpleNamespace(**kwargs),
          "MISS": "miss", "ERROR": "error", "_arg_query_list": lambda args, count: args["query"]}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "retrieve-scope", "exec"), ns)  # noqa: S102 - trusted repository functions
    result = asyncio.run(ns["execute_tool"](SimpleNamespace(), "retrieve", {"query": ["CAN"], "doc_scope": []}))
    assert result.status == "miss"
    assert result.payload == []
