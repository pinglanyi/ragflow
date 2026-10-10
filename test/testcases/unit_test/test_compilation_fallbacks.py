import importlib.util
import sys
import types
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]


def _load_module(monkeypatch, name: str, relative_path: str):
    common = types.ModuleType("common")
    common.__path__ = []
    common.settings = types.SimpleNamespace(docStoreConn=None)
    monkeypatch.setitem(sys.modules, "common", common)

    constants = types.ModuleType("common.constants")
    constants.LLMType = types.SimpleNamespace(CHAT="chat")
    monkeypatch.setitem(sys.modules, "common.constants", constants)

    misc = types.ModuleType("common.misc_utils")

    async def thread_pool_exec(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    misc.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, "common.misc_utils", misc)

    token_utils = types.ModuleType("common.token_utils")
    token_utils.num_tokens_from_string = lambda text: len(str(text).split())
    monkeypatch.setitem(sys.modules, "common.token_utils", token_utils)

    search = types.SimpleNamespace(index_name=lambda tenant_id: f"ragflow_{tenant_id}")
    nlp = types.ModuleType("rag.nlp")
    nlp.search = search
    nlp.rag_tokenizer = types.SimpleNamespace(
        tokenize=lambda text: str(text),
        fine_grained_tokenize=lambda text: str(text),
    )
    monkeypatch.setitem(sys.modules, "rag.nlp", nlp)

    redis_conn = types.ModuleType("rag.utils.redis_conn")

    class RedisDistributedLock:
        def __init__(self, *args, **kwargs):
            pass

        async def spin_acquire(self):
            return True

        def release(self):
            return None

    redis_conn.RedisDistributedLock = RedisDistributedLock
    monkeypatch.setitem(sys.modules, "rag.utils.redis_conn", redis_conn)

    compile_common = types.ModuleType("rag.advanced_rag.knowlege_compile._common")
    compile_common.encode = lambda *args, **kwargs: []
    compile_common.knowledge_compile_gen_conf = lambda _model, config: config
    monkeypatch.setitem(
        sys.modules,
        "rag.advanced_rag.knowlege_compile._common",
        compile_common,
    )

    task_context = types.ModuleType("rag.svr.task_executor_refactor.task_context")
    task_context.TaskContext = object
    monkeypatch.setitem(
        sys.modules,
        "rag.svr.task_executor_refactor.task_context",
        task_context,
    )

    wiki = types.ModuleType("rag.advanced_rag.knowlege_compile.wiki")
    wiki.wiki_map_from_chunks = None
    wiki.wiki_plan_from_reduction = None
    wiki.wiki_reduce_from_extracts = None
    wiki.wiki_refine_from_plan = None
    monkeypatch.setitem(sys.modules, "rag.advanced_rag.knowlege_compile.wiki", wiki)

    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_skill_roots_project_to_two_level_navigation(monkeypatch):
    module = _load_module(
        monkeypatch,
        "skill_generator_under_test",
        "rag/svr/task_executor_refactor/dataset_skill_generator.py",
    )
    leaf_a = module.SkillNode(
        level=0,
        label="a",
        summary="A summary",
        vec=np.asarray([1.0, 0.0]),
        doc_ids=["doc-a"],
        folder_name="group-a",
    )
    leaf_b = module.SkillNode(
        level=0,
        label="b",
        summary="B summary",
        vec=np.asarray([0.0, 1.0]),
        doc_ids=["doc-b"],
        folder_name="group-b",
    )
    root = module.SkillNode(
        level=1,
        label="root",
        summary="Root summary",
        vec=np.asarray([0.5, 0.5]),
        doc_ids=["doc-a", "doc-b"],
        children=[leaf_a, leaf_b],
        folder_name="skill-00-root",
    )

    result = module.nav_clusters_from_skill_roots(
        [root],
        {"doc-a": "A.pdf", "doc-b": "B.pdf"},
    )

    assert result[0]["name"] == "skill-00-root"
    assert result[0]["doc_ids"] == ["doc-a", "doc-b"]
    assert [doc["name"] for doc in result[0]["documents"]] == ["A.pdf", "B.pdf"]
    assert result[0]["documents"][0]["embedding"] == [1.0, 0.0]


def test_wiki_uses_builtin_template_when_documents_have_no_assignment(monkeypatch):
    module = _load_module(
        monkeypatch,
        "wiki_generator_under_test",
        "rag/svr/task_executor_refactor/dataset_wiki_generator.py",
    )
    module._parser_config_compilation_template_ids = lambda config, tenant_id: []

    document_service = types.ModuleType("api.db.services.document_service")
    document_service.DocumentService = types.SimpleNamespace(
        get_by_kb_id=lambda **kwargs: ([{"id": "doc-1", "name": "one.pdf"}], 1)
    )
    monkeypatch.setitem(sys.modules, "api.db.services.document_service", document_service)

    knowledgebase_service = types.ModuleType("api.db.services.knowledgebase_service")
    knowledgebase_service.KnowledgebaseService = types.SimpleNamespace(
        get_by_id=lambda kb_id: (
            True,
            types.SimpleNamespace(name="KB", description="description"),
        )
    )
    monkeypatch.setitem(sys.modules, "api.db.services.knowledgebase_service", knowledgebase_service)

    class TemplateService:
        @staticmethod
        def get_saved(template_id, tenant_id):
            return None

        @staticmethod
        def load_builtins_from_files():
            return [{"id": "wiki", "kind": "artifacts", "config": {"kind": "artifacts"}}]

        @staticmethod
        def fill_config_default_llm(config, tenant_id):
            return dict(config)

    template_service = types.ModuleType("api.db.services.compilation_template_service")
    template_service.CompilationTemplateService = TemplateService
    monkeypatch.setitem(
        sys.modules,
        "api.db.services.compilation_template_service",
        template_service,
    )

    llm_service = types.ModuleType("api.db.services.llm_service")
    llm_service.LLMBundle = lambda *args, **kwargs: object()
    monkeypatch.setitem(sys.modules, "api.db.services.llm_service", llm_service)

    tenant_models = types.ModuleType("api.db.joint_services.tenant_model_service")
    tenant_models.get_tenant_default_model_by_type = lambda *args: object()
    tenant_models.resolve_model_config = lambda *args: object()
    monkeypatch.setitem(
        sys.modules,
        "api.db.joint_services.tenant_model_service",
        tenant_models,
    )

    chunk_api = types.ModuleType("api.apps.restful_apis.chunk_api")
    chunk_api._compilation_template_kind = lambda kind: kind
    monkeypatch.setitem(sys.modules, "api.apps.restful_apis.chunk_api", chunk_api)

    mapped = []

    async def map_chunks(**kwargs):
        mapped.append(kwargs["doc_id"])
        return {"entities": [], "concepts": [], "claims": [], "relations": []}

    async def no_result(**kwargs):
        return None

    async def pages_result(**kwargs):
        return []

    module.wiki_map_from_chunks = map_chunks
    module.wiki_reduce_from_extracts = no_result
    module.wiki_plan_from_reduction = no_result
    module.wiki_refine_from_plan = pages_result
    module.persist_wiki_pages_to_es = no_result
    module.persist_wiki_page_graph_to_es = no_result

    progress_messages = []

    def progress(value=None, message="", msg=""):
        progress_messages.append(message or msg)

    ctx = types.SimpleNamespace(
        tenant_id="tenant-1",
        kb_id="kb-1",
        language="Chinese",
        progress_cb=progress,
    )

    async def chunks(*args, **kwargs):
        yield [{"id": "chunk-1", "content_with_weight": "content"}]

    import asyncio

    asyncio.run(module.run_wiki(ctx, object(), chunks))

    assert mapped == ["doc-1"]
    assert any("using built-in Wiki template" in message for message in progress_messages)


def test_replace_dataset_nav_from_clusters_writes_cluster_and_document(monkeypatch):
    module = _load_module(
        monkeypatch,
        "rag.advanced_rag.knowlege_compile.dataset_nav_under_test",
        "rag/advanced_rag/knowlege_compile/dataset_nav.py",
    )
    calls = []

    class DocStore:
        @staticmethod
        def delete(condition, index, kb_id):
            calls.append(("delete", condition, index, kb_id))

        @staticmethod
        def insert(rows, index, kb_id):
            calls.append(("insert", rows, index, kb_id))

    sys.modules["common"].settings.docStoreConn = DocStore()

    import asyncio
    import json

    count = asyncio.run(
        module.replace_dataset_nav_from_clusters(
            "tenant-1",
            "kb-1",
            [
                {
                    "name": "cluster-a",
                    "description": "Cluster A",
                    "doc_ids": ["doc-1"],
                    "embedding": [0.5, 0.5],
                    "children": [{
                        "name": "cluster-a/subtopic",
                        "display_name": "子主题",
                        "doc_ids": ["doc-2"],
                        "documents": [{"doc_id": "doc-2", "name": "two.pdf"}],
                    }],
                    "documents": [
                        {
                            "doc_id": "doc-1",
                            "name": "manual.pdf",
                            "description": "Manual summary",
                            "embedding": [1.0, 0.0],
                        }
                    ],
                }
            ],
        )
    )

    assert count == 4
    assert calls[0] == (
        "delete",
        {"compile_kwd": ["dataset_nav"]},
        "ragflow_tenant-1",
        "kb-1",
    )
    rows = calls[1][1]
    assert rows[0]["type_kwd"] == "nav_cluster"
    assert rows[1]["type_kwd"] == "nav_doc"
    assert rows[1]["doc_id"] == "doc-1"
    assert json.loads(rows[1]["content_with_weight"])["display_name"] == "manual.pdf"
    assert rows[2]["parent_kwd"] == "cluster-a"
    assert rows[2]["depth_int"] == 1
    assert json.loads(rows[2]["content_with_weight"])["display_name"] == "子主题"
    assert rows[3]["parent_kwd"] == "cluster-a/subtopic"
    assert rows[3]["depth_int"] == 2
