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


async def _async_value(value):
    return value


def test_request_aliases_and_limits():
    assert MODULE.validate_request({"keyword": " E502 接线 ", "mode": "term", "top_k": 30, "dataset_names": "产品库,kb-id,产品库"}) == {
        "keyword": "E502 接线", "mode": "term", "scan_meta": False, "top_k": 30, "dataset_refs": ["产品库", "kb-id"]
    }
    assert MODULE.validate_request({"keyword": "E502"}) == {
        "keyword": "E502", "mode": "phrase", "scan_meta": False, "top_k": 5, "dataset_refs": []
    }
    assert MODULE.validate_request({"query": "旧参数", "topkey": 2})["keyword"] == "旧参数"
    for payload in (
        {}, {"keyword": " "}, {"keyword": "a", "mode": "regex"}, {"keyword": "a", "top_k": 0},
        {"keyword": "a", "top_k": 31}, {"keyword": "a", "topkey": 2, "top_k": 3},
        {"keyword": "a", "query": "b"}, {"keyword": "a", "scan_meta": "yes"},
        {"keyword": "a", "dataset_names": ["产品库"]},
        {"keyword": "a", "dataset_names": "产品库", "dataset_ids": "kb"}, {"keyword": "a", "unknown": True},
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


def test_filename_candidates_use_hybrid_retrieval_with_dominant_filename_weight(monkeypatch):
    calls = []

    class Retriever:
        async def retrieval(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"chunks": [
                {"document_id": "doc1", "similarity": 0.74},
                {"document_id": "doc1", "similarity": 0.91},
                {"document_id": "doc2", "similarity": 0.63},
            ]}

    model_module = ModuleType("api.db.joint_services.tenant_model_service")
    model_module.resolve_model_config = lambda tenant_id, model_type, embd_id: {"id": embd_id}
    llm_module = ModuleType("api.db.services.llm_service")
    llm_module.LLMBundle = lambda tenant_id, config: (tenant_id, config)
    settings_module = ModuleType("common.settings")
    settings_module.retriever = Retriever()
    constants_module = ModuleType("common.constants")
    constants_module.LLMType = SimpleNamespace(EMBEDDING="embedding")
    search_module = SimpleNamespace(index_name=lambda tenant_id: f"ragflow_{tenant_id}")
    nlp_module = ModuleType("rag.nlp")
    nlp_module.search = search_module
    for module in (model_module, llm_module, settings_module, constants_module, nlp_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    result = asyncio.run(MODULE._retrieve_filename_candidates([
        {"id": "kb1", "tenant_id": "tenant", "embd_id": "embed", "chunk_num": 3},
    ], "E502 接线", 5))

    assert result == {"doc1": 0.91, "doc2": 0.63}
    args, kwargs = calls[0]
    assert args[0] == "E502 接线"
    assert args[2:4] == (["tenant"], ["kb1"])
    assert kwargs["vector_similarity_weight"] == 0.15
    assert kwargs["filename_token_weight"] == 20
    assert kwargs["query_fields"][0] == "docnm_kwd^200"


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

    def search(ids, keyword, mode, top_k, *, unparsed_only=False):
        calls.append((ids, keyword, mode, top_k, unparsed_only))
        return [docs[0]]

    def metadata(ids, kb_id):
        return {"doc1": {"author": "张三", "doc_id": "spoof", "datasetid": "spoof", "location": "spoof"}} if kb_id == "kb1" else {}

    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(
        search_by_name=search,
        get_name_retrieval_documents=lambda kb_ids, doc_ids: [docs[1]] if doc_ids == ["doc2"] else [],
    )
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(
        get_metadata_for_documents=metadata,
        filter_doc_ids_by_meta_pushdown=lambda *args: (_ for _ in ()).throw(
            AssertionError("scan_meta=false must not search all document descriptions")
        ),
    )
    misc_module = ModuleType("common.misc_utils")
    misc_module.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    for module in (document_module, metadata_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(MODULE, "_visible_datasets", visible)
    monkeypatch.setattr(MODULE, "_retrieve_filename_candidates", lambda *args: _async_value({"doc2": 0.82}))

    result = asyncio.run(MODULE.find_source_files({"keyword": "E502", "top_k": 2}, user_id="user"))
    assert calls == [(["kb1", "kb2"], "E502", "phrase", 2, True)]
    assert result["count"] == 2
    assert result["searched_dataset_count"] == 2
    doc1 = next(row for row in result["documents"] if row["metafield"]["doc_id"] == "doc1")
    assert doc1 == {"file_name": "E502手册.pdf", "matched_by": ["file_name"], "metafield": {
        "author": "张三", "datasetid": "kb1", "docid": "doc1", "dataset_id": "kb1", "dataset_name": "产品库", "doc_id": "doc1", "location": "folder/E502手册.pdf"
    }}
    assert {row["metafield"]["doc_id"] for row in result["documents"]} == {"doc1", "doc2"}


def test_semantic_retrieval_candidate_survives_phrase_mode_without_literal_name_match(monkeypatch):
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库", "tenant_id": "tenant", "embd_id": "embedding", "chunk_num": 2}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    semantic_doc = {
        "id": "semantic", "kb_id": "kb1", "name": "温度采集模块说明书.pdf", "location": "manual.pdf"
    }
    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(
        search_by_name=lambda *args, **kwargs: [],
        get_name_retrieval_documents=lambda kb_ids, doc_ids: [semantic_doc],
    )
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(get_metadata_for_documents=lambda *args: {})
    misc_module = ModuleType("common.misc_utils")
    misc_module.thread_pool_exec = thread_pool_exec
    for module in (document_module, metadata_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(MODULE, "_visible_datasets", visible)
    monkeypatch.setattr(
        MODULE, "_retrieve_filename_candidates", lambda *args: _async_value({"semantic": 0.91})
    )

    result = asyncio.run(MODULE.find_source_files({"keyword": "E502 接线", "mode": "phrase"}, user_id="user"))

    assert result["count"] == 1
    assert result["documents"][0]["file_name"] == "温度采集模块说明书.pdf"
    assert result["documents"][0]["matched_by"] == ["retrieval"]


def test_term_mode_ranks_partial_filename_match_above_pure_semantic_candidate(monkeypatch):
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库", "tenant_id": "tenant", "embd_id": "embedding", "chunk_num": 2}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    docs = {
        "semantic": {"id": "semantic", "kb_id": "kb1", "name": "系统方案.pdf", "location": "system.pdf"},
        "partial": {"id": "partial", "kb_id": "kb1", "name": "E502模块规格书.pdf", "location": "E502.pdf"},
    }
    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(
        search_by_name=lambda *args, **kwargs: [],
        get_name_retrieval_documents=lambda kb_ids, doc_ids: [docs[doc_id] for doc_id in doc_ids],
    )
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(get_metadata_for_documents=lambda *args: {})
    misc_module = ModuleType("common.misc_utils")
    misc_module.thread_pool_exec = thread_pool_exec
    for module in (document_module, metadata_module, misc_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(MODULE, "_visible_datasets", visible)
    monkeypatch.setattr(
        MODULE, "_retrieve_filename_candidates", lambda *args: _async_value({"semantic": 0.99, "partial": 0.5})
    )

    result = asyncio.run(MODULE.find_source_files({
        "keyword": "E502 温度采集", "mode": "term", "top_k": 2,
    }, user_id="user"))

    assert [row["metafield"]["docid"] for row in result["documents"]] == ["partial", "semantic"]
    assert result["documents"][0]["matched_by"] == ["retrieval"]


def test_retrieval_rejects_a_document_outside_authorized_scope(monkeypatch):
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库"}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(search_by_name=lambda *args, **kwargs: [
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
    monkeypatch.setattr(MODULE, "_retrieve_filename_candidates", lambda *args: _async_value({}))

    with pytest.raises(ValueError, match="authorized scope"):
        asyncio.run(MODULE.find_source_files({"keyword": "E502"}, user_id="user"))


def test_description_only_metadata_finds_file_without_name_or_chunks(monkeypatch):
    async def visible(user_id):
        return [{"id": "kb1", "name": "产品库", "tenant_id": "tenant"}]

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    doc = {"id": "manual", "kb_id": "kb1", "name": "产品说明.pdf", "location": "folder/manual.pdf", "chunk_num": 0}
    document_module = ModuleType("api.db.services.document_service")
    document_module.DocumentService = SimpleNamespace(
        search_by_name=lambda *args, **kwargs: [],
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
    monkeypatch.setattr(MODULE, "_retrieve_filename_candidates", lambda *args: _async_value({}))

    result = asyncio.run(MODULE.find_source_files({"keyword": "E502", "scan_meta": True}, user_id="user"))
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
        search_by_name=lambda *args, **kwargs: [],
        get_name_retrieval_documents=lambda kb_ids, doc_ids: (
            name_docs if doc_ids == ["exact", "prefix", "both"] else description_docs
        ),
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
    monkeypatch.setattr(
        MODULE, "_retrieve_filename_candidates", lambda *args: _async_value({"exact": 0.7, "prefix": 0.8, "both": 0.9})
    )

    result = asyncio.run(MODULE.find_source_files({"keyword": "E502", "scan_meta": True, "top_k": 4}, user_id="user"))
    assert [row["metafield"]["docid"] for row in result["documents"]] == [
        "exact", "prefix", "both", "description",
    ]
    assert result["documents"][2]["matched_by"] == ["file_name", "description"]


def test_description_lookup_falls_back_when_pushdown_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    service = SimpleNamespace(
        filter_doc_ids_by_meta_pushdown=lambda *args: None,
        get_flatted_meta_by_kbs=lambda ids: {"description": {"E502 温度采集": ["doc1"], "E503": ["doc2"]}},
    )

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    result = asyncio.run(MODULE._description_ids([{"id": "kb1", "tenant_id": "tenant"}], "E502", "phrase", service, thread_pool_exec))
    assert result == ["doc1"]


def test_infinity_description_lookup_scans_metadata_values(monkeypatch):
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=True))
    service = SimpleNamespace(
        filter_doc_ids_by_meta_pushdown=lambda *args: (_ for _ in ()).throw(AssertionError("wrong backend path")),
        get_flatted_meta_by_kbs=lambda ids: {"描述": {"E502 温度采集模块": ["doc1"]}},
    )

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    assert asyncio.run(MODULE._description_ids([{"id": "kb1", "tenant_id": "tenant"}], "温度", "phrase", service, thread_pool_exec)) == ["doc1"]


def test_term_description_requires_all_whitespace_delimited_terms(monkeypatch):
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=True))
    service = SimpleNamespace(get_flatted_meta_by_kbs=lambda ids: {
        "description": {
            "E502 温度采集模块接线说明": ["all"],
            "E502 通讯模块": ["first"],
            "温度采集模块": ["second"],
        }
    })

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    result = asyncio.run(MODULE._description_ids(
        [{"id": "kb1", "tenant_id": "tenant"}], "E502 温度", "term", service, thread_pool_exec
    ))
    assert result == ["all"]


def test_term_description_pushdown_ands_terms_within_each_description_field(monkeypatch):
    monkeypatch.setitem(sys.modules, "common.settings", SimpleNamespace(DOC_ENGINE_INFINITY=False))
    calls = []

    def pushdown(kb_ids, filters, logic, limit):
        calls.append((filters, logic))
        return ["doc1"] if filters[0]["key"] == "description" else []

    service = SimpleNamespace(filter_doc_ids_by_meta_pushdown=pushdown)

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    result = asyncio.run(MODULE._description_ids(
        [{"id": "kb1", "tenant_id": "tenant"}], "E502 接线", "term", service, thread_pool_exec
    ))
    assert result == ["doc1"]
    assert len(calls) == 3
    assert all(logic == "and" for _, logic in calls)
    assert calls[0][0] == [
        {"key": "description", "op": "contains", "value": "e502"},
        {"key": "description", "op": "contains", "value": "接线"},
    ]
