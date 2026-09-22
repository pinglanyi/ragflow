"""Document-name retrieval contract without a running database."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[5] / "api/apps/services/agentic_search_document_service.py"
SPEC = importlib.util.spec_from_file_location("agentic_search_document_service_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_request_aliases_and_limits():
    assert MODULE.validate_request({"query": " E502 ", "topkey": 3, "dataset_names": "产品库,kb-id,产品库"}) == {
        "query": "E502", "top_k": 3, "dataset_refs": ["产品库", "kb-id"]
    }
    assert MODULE.validate_request({"query": "E502"}) == {"query": "E502", "top_k": 5, "dataset_refs": []}
    for payload in (
        {}, {"query": " "}, {"query": "a", "top_k": 0}, {"query": "a", "topkey": 21},
        {"query": "a", "topkey": 2, "top_k": 3}, {"query": "a", "dataset_names": ["产品库"]},
        {"query": "a", "dataset_names": "产品库", "dataset_ids": "kb"}, {"query": "a", "unknown": True},
    ):
        with pytest.raises(ValueError):
            MODULE.validate_request(payload)


def test_scope_resolves_visible_names_ids_and_rejects_ambiguity():
    catalog = [{"id": "kb1", "name": "产品库"}, {"id": "kb2", "name": "文件库"}]
    assert MODULE.resolve_scope(["产品库", "kb2", "kb1"], catalog) == [catalog[0], catalog[1]]
    assert MODULE.resolve_scope([], catalog) == catalog
    with pytest.raises(PermissionError):
        MODULE.resolve_scope(["private"], catalog)
    with pytest.raises(ValueError, match="ambiguous"):
        MODULE.resolve_scope(["重名"], [{"id": "one", "name": "重名"}, {"id": "two", "name": "重名"}])


def test_retrieval_merges_document_metadata_without_chunk_lookup(monkeypatch):
    calls = []
    docs = [
        {"id": "doc1", "kb_id": "kb1", "name": "E502手册.pdf", "location": "folder/E502手册.pdf", "chunk_num": 0},
        {"id": "doc2", "kb_id": "kb2", "name": "E502配置.pdf", "location": "E502配置.pdf", "chunk_num": 2},
    ]
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库"}, {"id": "kb2", "name": "文件库"}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def search(ids, query, top_k):
        calls.append((ids, query, top_k))
        return docs

    def metadata(ids, kb_id):
        return {"doc1": {"author": "张三", "doc_id": "spoof", "datasetid": "spoof", "location": "spoof"}} if kb_id == "kb1" else {}

    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(search_by_name=search, get_name_retrieval_documents=lambda *args: [])
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(
        get_metadata_for_documents=metadata,
        filter_doc_ids_by_meta_pushdown=lambda *args: [],
    )
    misc_module = ModuleType("common.misc_utils")
    misc_module.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    for module in (document_module, metadata_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(MODULE, "_visible_datasets", visible)

    result = asyncio.run(MODULE.retrieve_documents_by_name({"query": "E502", "top_k": 2}, user_id="user"))
    assert calls == [(["kb1", "kb2"], "E502", 2)]
    assert result["count"] == 2
    assert result["searched_dataset_count"] == 2
    assert result["documents"][0] == {"file_name": "E502手册.pdf", "matched_by": ["file_name"], "metafield": {
        "author": "张三", "datasetid": "kb1", "docid": "doc1", "dataset_id": "kb1", "dataset_name": "产品库", "doc_id": "doc1", "location": "folder/E502手册.pdf"
    }}
    assert result["documents"][1]["metafield"]["doc_id"] == "doc2"


def test_retrieval_rejects_a_document_outside_authorized_scope(monkeypatch):
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库"}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(search_by_name=lambda *args: [
        {"id": "private-doc", "kb_id": "private-kb", "name": "E502.pdf", "location": "E502.pdf"}
    ], get_name_retrieval_documents=lambda *args: [])
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(
        get_metadata_for_documents=lambda *args: {}, filter_doc_ids_by_meta_pushdown=lambda *args: [],
    )
    misc_module = ModuleType("common.misc_utils")
    misc_module.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    for module in (document_module, metadata_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(MODULE, "_visible_datasets", visible)

    with pytest.raises(ValueError, match="authorized scope"):
        asyncio.run(MODULE.retrieve_documents_by_name({"query": "E502"}, user_id="user"))


def test_description_only_metadata_finds_file_without_name_or_chunks(monkeypatch):
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库", "tenant_id": "tenant"}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    doc = {"id": "manual", "kb_id": "kb1", "name": "产品说明.pdf", "location": "folder/manual.pdf", "chunk_num": 0}
    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(
        search_by_name=lambda *args: [],
        get_name_retrieval_documents=lambda kb_ids, doc_ids: [doc] if doc_ids == ["manual"] else [],
    )
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(
        filter_doc_ids_by_meta_pushdown=lambda kb_ids, filters, logic, limit: ["manual"],
        get_metadata_for_documents=lambda ids, kb_id: {"manual": {"description": "E502 温度采集模块接线说明"}},
    )
    misc_module = ModuleType("common.misc_utils")
    misc_module.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    for module in (document_module, metadata_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(MODULE, "_visible_datasets", visible)

    result = asyncio.run(MODULE.retrieve_documents_by_name({"query": "E502"}, user_id="user"))
    assert result["count"] == 1
    assert result["documents"][0]["file_name"] == "产品说明.pdf"
    assert result["documents"][0]["matched_by"] == ["description"]
    assert result["documents"][0]["metafield"]["description"] == "E502 温度采集模块接线说明"


def test_file_name_and_description_candidates_are_deduplicated_and_ranked(monkeypatch):
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库", "tenant_id": "tenant"}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def doc(doc_id, name):
        return {"id": doc_id, "kb_id": "kb1", "name": name, "location": name}

    name_docs = [doc("exact", "E502"), doc("prefix", "E502手册.pdf"), doc("both", "电气E502.pdf")]
    description_docs = [doc("description", "接线说明.pdf"), name_docs[2]]
    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(
        search_by_name=lambda *args: name_docs,
        get_name_retrieval_documents=lambda *args: description_docs,
    )
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(
        filter_doc_ids_by_meta_pushdown=lambda *args: ["description", "both"],
        get_metadata_for_documents=lambda ids, kb_id: {
            doc_id: {"description": "E502 接线说明"} for doc_id in ids if doc_id in {"description", "both"}
        },
    )
    misc_module = ModuleType("common.misc_utils")
    misc_module.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    for module in (document_module, metadata_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(MODULE, "_visible_datasets", visible)

    result = asyncio.run(MODULE.retrieve_documents_by_name({"query": "E502", "top_k": 4}, user_id="user"))
    assert [row["metafield"]["docid"] for row in result["documents"]] == [
        "exact", "prefix", "description", "both",
    ]
    assert result["documents"][-1]["matched_by"] == ["file_name", "description"]


def test_description_lookup_falls_back_when_pushdown_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    service = SimpleNamespace(
        filter_doc_ids_by_meta_pushdown=lambda *args: None,
        get_flatted_meta_by_kbs=lambda ids: {"description": {"E502 温度采集": ["doc1"], "E503": ["doc2"]}},
    )

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    result = asyncio.run(MODULE._description_ids([{"id": "kb1", "tenant_id": "tenant"}], "E502", service, thread_pool_exec))
    assert result == ["doc1"]


def test_infinity_description_lookup_scans_metadata_values(monkeypatch):
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=True))
    service = SimpleNamespace(
        filter_doc_ids_by_meta_pushdown=lambda *args: (_ for _ in ()).throw(AssertionError("wrong backend path")),
        get_flatted_meta_by_kbs=lambda ids: {"描述": {"E502 温度采集模块": ["doc1"]}},
    )

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    assert asyncio.run(MODULE._description_ids([{"id": "kb1", "tenant_id": "tenant"}], "温度", service, thread_pool_exec)) == ["doc1"]
