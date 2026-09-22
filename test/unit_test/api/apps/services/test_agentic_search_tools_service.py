"""Mistral-style Agentic Search tool contract without a running database."""

import importlib.util
import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[5] / "api/apps/services/agentic_search_tools_service.py"
SPEC = importlib.util.spec_from_file_location("agentic_search_tools_service_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("name", ["search", "open", "navigate", "read", "grep", "ingest", "delete"])
def test_all_native_tools_have_validated_contracts(name):
    assert name in MODULE.TOOL_NAMES
    with pytest.raises(ValueError):
        MODULE.validate_tool_request(name, {})


def test_search_defaults_and_comma_separated_dataset_ids():
    request = MODULE.validate_tool_request("search", {"query": " CAN 接线 ", "dataset_ids": " a, b,a ", "exclude_ids": ["x", "x"]})
    assert request == {"query": "CAN 接线", "top_k": 5, "exclude_ids": ["x"], "dataset_ids": ["a", "b"]}


def test_search_accepts_comma_separated_dataset_names_or_ids():
    request = MODULE.validate_tool_request("search", {
        "query": "E502", "dataset_names": " 产品库,982c06185fc011f1ae03d7c376fa307f,产品库 "
    })
    assert request["dataset_ids"] == ["产品库", "982c06185fc011f1ae03d7c376fa307f"]
    with pytest.raises(ValueError, match="both"):
        MODULE.validate_tool_request("search", {"query": "E502", "dataset_names": "产品库", "dataset_ids": "kb"})


def test_search_resolves_visible_names_and_ids_without_scope_widening(monkeypatch):
    catalog = [
        {"id": "kb-product", "name": "产品库"},
        {"id": "kb-file", "name": "文件库"},
    ]
    async def accessible(user_id):
        return catalog
    async def validate(*, dataset_ids, user_id):
        assert dataset_ids == ["kb-product", "kb-file"]
        return [{"id": item, "name": next(row["name"] for row in catalog if row["id"] == item)} for item in dataset_ids]
    api_module = ModuleType("api.apps.services.agentic_search_api_service")
    api_module.validate_explicit_dataset_scope = validate
    monkeypatch.setitem(sys.modules, api_module.__name__, api_module)
    monkeypatch.setattr(MODULE, "_accessible_catalog", accessible)
    ids, mode, selected = asyncio.run(MODULE._search_scope("user", "E502", ["产品库", "kb-file", "kb-product"]))
    assert ids == ["kb-product", "kb-file"]
    assert mode == "manual" and [row["id"] for row in selected] == ids
    with pytest.raises(PermissionError):
        asyncio.run(MODULE._search_scope("user", "E502", ["不存在的库"]))


def test_search_rejects_ambiguous_dataset_name(monkeypatch):
    async def accessible(user_id):
        return [{"id": "one", "name": "同名"}, {"id": "two", "name": "同名"}]
    api_module = ModuleType("api.apps.services.agentic_search_api_service")
    api_module.validate_explicit_dataset_scope = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, api_module.__name__, api_module)
    monkeypatch.setattr(MODULE, "_accessible_catalog", accessible)
    with pytest.raises(ValueError, match="ambiguous"):
        asyncio.run(MODULE._search_scope("user", "E502", ["同名"]))


@pytest.mark.parametrize("payload", [
    {"query": "x", "top_k": 0},
    {"query": "x", "exclude_ids": "a"},
    {"query": "x", "dataset_ids": ["a"]},
    {"query": "x", "dataset_names": ["a"]},
    {"query": "x", "unknown": 1},
])
def test_search_rejects_invalid_arguments(payload):
    with pytest.raises(ValueError):
        MODULE.validate_tool_request("search", payload)


def test_navigation_requires_valid_ordinal_range_and_direction():
    assert MODULE.validate_tool_request("navigate", {
        "source_id": "doc", "start_offset": 2, "end_offset": 2, "direction": "previous"
    })["top_k"] == 1
    with pytest.raises(ValueError):
        MODULE.validate_tool_request("navigate", {
            "source_id": "doc", "start_offset": 3, "end_offset": 2, "direction": "next"
        })
    with pytest.raises(ValueError):
        MODULE.validate_tool_request("navigate", {
            "source_id": "doc", "start_offset": 2, "end_offset": 2, "direction": "up"
        })


def test_normalized_chunk_keeps_source_coordinates():
    chunk = MODULE.normalize_chunk({
        "chunk_id": "ck", "doc_id": "doc", "kb_id": "kb", "content_with_weight": "原文",
        "docnm_kwd": "手册.pdf", "positions": [[2, 0, 0, 3, 4]], "similarity": 0.7,
        "chunk_order": 4,
    })
    assert chunk["id"] == "ck"
    assert chunk["source_id"] == "doc"
    assert chunk["start_offset"] == chunk["end_offset"] == 4
    assert chunk["metadata"]["coordinate"] == "visible_chunk_ordinal"
    assert chunk["content"] == "原文"
    assert chunk["score"] == 0.7
    assert chunk["metadata"]["navigable"] is True


def test_legacy_chunk_without_order_is_identified_as_not_navigable():
    chunk = MODULE.normalize_chunk({"chunk_id": "legacy", "doc_id": "doc"})
    assert chunk["start_offset"] is None
    assert chunk["metadata"]["navigable"] is False


def test_write_tools_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("RAGFLOW_AGENTIC_SEARCH_WRITE_TOOLS_ENABLED", raising=False)
    with pytest.raises(PermissionError):
        MODULE.require_write_tools_enabled()
    monkeypatch.setenv("RAGFLOW_AGENTIC_SEARCH_WRITE_TOOLS_ENABLED", "true")
    MODULE.require_write_tools_enabled()


def test_ingest_uri_rejects_unlisted_sources(monkeypatch, tmp_path):
    monkeypatch.delenv("RAGFLOW_AGENTIC_SEARCH_INGEST_ROOT", raising=False)
    monkeypatch.delenv("RAGFLOW_AGENTIC_SEARCH_ALLOWED_URL_HOSTS", raising=False)
    with pytest.raises(PermissionError):
        MODULE.resolve_ingest_uri(str(tmp_path / "doc.pdf"))
    with pytest.raises(PermissionError):
        MODULE.resolve_ingest_uri("https://example.com/doc.pdf")


def _ordered_chunks():
    return [{"chunk_id": f"ck-{i}", "doc_id": "doc", "kb_id": "kb", "chunk_order": i,
             "content_with_weight": f"text {i}", "positions": [[i + 1, 0, 0, 0, 0]]} for i in range(5)]


def test_open_returns_anchor_and_symmetric_neighbours():
    result = MODULE.select_open_chunks(_ordered_chunks(), "ck-2", 1)
    assert [item["id"] for item in result] == ["ck-1", "ck-2", "ck-3"]
    with pytest.raises(ValueError, match="chunk"):
        MODULE.select_open_chunks(_ordered_chunks(), "missing", 1)


def test_navigate_and_read_follow_document_order():
    chunks = _ordered_chunks()
    assert [item["id"] for item in MODULE.select_navigate_chunks(chunks, 2, 2, "next", 2)] == ["ck-3", "ck-4"]
    assert [item["id"] for item in MODULE.select_navigate_chunks(chunks, 2, 2, "previous", 2)] == ["ck-0", "ck-1"]
    assert [item["id"] for item in MODULE.select_read_chunks(chunks, 1, 3, 20)] == ["ck-1", "ck-2", "ck-3"]


def test_grep_supports_phrase_and_all_terms():
    chunks = _ordered_chunks()
    chunks[0]["content_with_weight"] = "CAN 接线 接地"
    chunks[1]["content_with_weight"] = "接地 CAN 接线"
    assert [item["id"] for item in MODULE.select_grep_chunks(chunks, "CAN 接线", "phrase", 5)] == ["ck-0", "ck-1"]
    assert [item["id"] for item in MODULE.select_grep_chunks(chunks, "CAN 接地", "term", 5)] == ["ck-0", "ck-1"]


def test_search_forwards_exclusions_and_preserves_chunk_order(monkeypatch):
    calls = []
    search_module = ModuleType("rag.advanced_rag.harness.tools.search")

    async def hybrid_search(tools, query, **kwargs):
        calls.append((query, kwargs))
        return {"chunks": [{"chunk_id": "ck-1", "doc_id": "doc", "kb_id": "kb", "content_with_weight": "正文"}]}

    search_module.hybrid_search = hybrid_search
    monkeypatch.setitem(sys.modules, "rag.advanced_rag.harness.tools.search", search_module)

    async def scope(user_id, query, dataset_ids):
        return ["kb"], "manual", [{"id": "kb"}]

    async def tools(user_id, dataset_ids, *, embedding=False):
        return SimpleNamespace()

    async def ordered(tools, source_id):
        return [{"chunk_id": "ck-1", "chunk_order": 3}]

    monkeypatch.setattr(MODULE, "_search_scope", scope)
    monkeypatch.setattr(MODULE, "_authorized_tools", tools)
    monkeypatch.setattr(MODULE, "_ordered_document", ordered)
    result = asyncio.run(MODULE.execute_tool("search", {
        "query": "CAN", "dataset_ids": "kb", "exclude_ids": ["seen"]
    }, user_id="user"))
    assert calls[0][1]["exclude_ids"] == ["seen"]
    assert result["chunks"][0]["start_offset"] == 3
    assert result["selected_datasets"] == [{"id": "kb"}]


def test_execute_write_tool_denied_before_side_effects(monkeypatch):
    monkeypatch.delenv("RAGFLOW_AGENTIC_SEARCH_WRITE_TOOLS_ENABLED", raising=False)
    with pytest.raises(PermissionError, match="disabled"):
        asyncio.run(MODULE.execute_tool("delete", {"source_id": "doc"}, user_id="user"))


def test_authorized_tools_include_indexed_field_mapped_dataset(monkeypatch):
    captured = {}
    kb = SimpleNamespace(id="kb", tenant_id="tenant", parser_config={"field_map": {"model": "model"}})
    kb_module = ModuleType("api.db.services.knowledgebase_service")
    kb_module.KnowledgebaseService = SimpleNamespace(
        accessible=lambda **kwargs: True,
        get_by_ids=lambda ids: [kb],
    )
    kb_module.validate_dataset_embedding_models = lambda kbs: None
    misc_module = ModuleType("common.misc_utils")

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    misc_module.thread_pool_exec = thread_pool_exec
    rag_module = ModuleType("rag.advanced_rag.agentic_rag")

    def rag_tools(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(kb_ids=kwargs["kb_ids"])

    rag_module.RAGTools = rag_tools
    for module in (kb_module, misc_module, rag_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    asyncio.run(MODULE._authorized_tools("user", ["kb"]))
    assert captured["include_field_mapped_kbs"] is True


def test_delete_checks_owner_and_removes_only_one_document(monkeypatch):
    deleted = []
    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(query=lambda **kwargs: [SimpleNamespace(kb_id="kb")])
    file_module = ModuleType("api.db.services.file_service")
    file_module.FileService = SimpleNamespace(delete_docs=lambda ids, user: deleted.append((ids, user)) or "")
    kb_module = ModuleType("api.db.services.knowledgebase_service")
    kb_module.KnowledgebaseService = SimpleNamespace(accessible4deletion=lambda kb, user: user == "owner")
    misc_module = ModuleType("common.misc_utils")

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    misc_module.thread_pool_exec = thread_pool_exec
    for module in (document_module, file_module, kb_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(PermissionError):
        asyncio.run(MODULE._delete("outsider", {"source_id": "doc"}))
    assert deleted == []
    result = asyncio.run(MODULE._delete("owner", {"source_id": "doc"}))
    assert result["deleted"] is True
    assert deleted == [(["doc"], "owner")]


def test_ingest_checks_owner_and_queues_uploaded_document(monkeypatch):
    queued = []
    uploaded = []
    kb = SimpleNamespace(id="kb", tenant_id="tenant")
    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(run=lambda tenant, doc, counts: queued.append((tenant, doc["id"])))
    file_module = ModuleType("api.db.services.file_service")

    def upload(kb, files, user):
        uploaded.append((files[0].filename, files[0].read(), user))
        return [], [({"id": "new-doc", "name": "manual.pdf"}, b"pdf")]

    file_module.FileService = SimpleNamespace(upload_document=upload)
    kb_module = ModuleType("api.db.services.knowledgebase_service")
    kb_module.KnowledgebaseService = SimpleNamespace(
        accessible4deletion=lambda kb_id, user: user == "owner",
        get_by_id=lambda kb_id: (True, kb),
    )
    misc_module = ModuleType("common.misc_utils")

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    misc_module.thread_pool_exec = thread_pool_exec
    for module in (document_module, file_module, kb_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    async def blobs(uri):
        return [("manual.pdf", b"pdf")]

    monkeypatch.setattr(MODULE, "_ingest_blobs", blobs)
    with pytest.raises(PermissionError):
        asyncio.run(MODULE._ingest("outsider", {"uri": "file", "dataset_id": "kb"}))
    assert uploaded == []
    result = asyncio.run(MODULE._ingest("owner", {"uri": "file", "dataset_id": "kb"}))
    assert uploaded == [("manual.pdf", b"pdf", "owner")]
    assert queued == [("tenant", "new-doc")]
    assert result["documents"][0]["parse_status"] == "QUEUED"
