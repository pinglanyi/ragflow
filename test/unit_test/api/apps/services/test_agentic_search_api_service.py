import importlib.util
import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[5] / "api" / "apps" / "services" / "agentic_search_api_service.py"
SPEC = importlib.util.spec_from_file_location("agentic_search_api_service_under_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

apply_dialog_overrides = MODULE.apply_dialog_overrides
normalize_agentic_search_result = MODULE.normalize_agentic_search_result
validate_agentic_search_request = MODULE.validate_agentic_search_request


def test_validate_requires_query_and_search_scope():
    with pytest.raises(ValueError, match="query"):
        validate_agentic_search_request({"chat_id": "chat-1"})
    with pytest.raises(ValueError, match="chat_id.*dataset_ids"):
        validate_agentic_search_request({"query": "hello"})


def test_validate_accepts_stateless_dataset_scope_and_rejects_session():
    result = validate_agentic_search_request({"query": "hello", "dataset_ids": [" kb-1 ", "kb-1"]})
    assert result["dataset_ids"] == ["kb-1"]
    assert result.get("chat_id") is None

    with pytest.raises(ValueError, match="session_id.*chat_id"):
        validate_agentic_search_request({"query": "hello", "dataset_ids": ["kb-1"], "session_id": "session-1"})


def test_build_stateless_dialog_uses_knowledge_prompt_and_overrides():
    dialog = MODULE.build_stateless_dialog(
        tenant_id="tenant-1",
        dataset_ids=["kb-1"],
        model="model-1",
        options={"top_n": 4, "similarity_threshold": 0.35},
    )
    assert dialog.tenant_id == "tenant-1"
    assert dialog.kb_ids == ["kb-1"]
    assert dialog.llm_id == "model-1"
    assert dialog.top_n == 4
    assert dialog.similarity_threshold == 0.35
    assert "{knowledge}" in dialog.prompt_config["system"]


def test_validate_rejects_unknown_fields_and_invalid_reasoning():
    with pytest.raises(ValueError, match="unknown"):
        validate_agentic_search_request({"query": "hello", "chat_id": "chat-1", "unknown": True})
    with pytest.raises(ValueError, match="reasoning"):
        validate_agentic_search_request({"query": "hello", "chat_id": "chat-1", "reasoning": 5})


def test_validate_normalizes_defaults_and_dataset_ids():
    result = validate_agentic_search_request(
        {
            "query": "  hello  ",
            "chat_id": "chat-1",
            "dataset_ids": ["kb-1", "kb-1", "", "kb-2"],
        }
    )
    assert result["query"] == "hello"
    assert result["reasoning"] == 3
    assert result["dataset_ids"] == ["kb-1", "kb-2"]


def test_apply_dialog_overrides_does_not_mutate_source():
    source = SimpleNamespace(kb_ids=["a"], llm_id="old", top_n=8, similarity_threshold=0.2)
    copied = apply_dialog_overrides(
        source,
        {"dataset_ids": ["b"], "model": "new", "top_n": 3, "similarity_threshold": 0.4},
    )
    assert source.kb_ids == ["a"]
    assert source.llm_id == "old"
    assert copied.kb_ids == ["b"]
    assert copied.llm_id == "new"
    assert copied.top_n == 3
    assert copied.similarity_threshold == 0.4


def test_normalize_agentic_search_result_flattens_references():
    raw = {
        "answer": "answer",
        "session_id": "session-1",
        "reference": {
            "chunks": [
                {
                    "id": "chunk-1",
                    "dataset_id": "kb-1",
                    "document_id": "doc-1",
                    "document_name": "manual.pdf",
                    "content": "evidence",
                    "similarity": 0.9,
                    "positions": [[1, 2, 3]],
                    "image_id": "image-1",
                    "url": None,
                }
            ]
        },
    }
    normalized = normalize_agentic_search_result(
        raw,
        request_id="request-1",
        chat_id="chat-1",
        model="model-1",
        reasoning=3,
        elapsed_ms=42,
    )
    assert normalized["answer"] == "answer"
    assert normalized["reference_count"] == 1
    assert normalized["references"][0]["chunk_id"] == "chunk-1"
    assert normalized["references"][0]["document_name"] == "manual.pdf"
    assert normalized["request_id"] == "request-1"


def test_execute_agentic_search_uses_request_scoped_dialog_copy(monkeypatch):
    source = SimpleNamespace(
        id="chat-1",
        tenant_id="tenant-1",
        kb_ids=["stored-kb"],
        llm_id="stored-model",
        tenant_llm_id=None,
        top_n=8,
        similarity_threshold=0.2,
        prompt_config={"prologue": "hello"},
    )
    conversation = SimpleNamespace(
        id="session-1",
        dialog_id="chat-1",
        user_id="tenant-1",
        message=[],
        reference=[],
        to_dict=lambda: {},
    )
    captured = {}

    class DialogService:
        @staticmethod
        def query(**_kwargs):
            return [source]

    class ConversationService:
        @staticmethod
        def get_by_id(_session_id):
            return True, conversation

        @staticmethod
        def update_by_id(*_args):
            return True

    class KnowledgebaseService:
        @staticmethod
        def accessible(**_kwargs):
            return True

        @staticmethod
        def query(**_kwargs):
            return [SimpleNamespace(chunk_num=1)]

    async def rag_agent(dialog, messages, _stream, **_kwargs):
        captured["dialog"] = dialog
        captured["messages"] = messages
        yield {
            "answer": "done",
            "reference": {"chunks": [{"id": "chunk-1", "document_name": "manual.pdf"}]},
        }

    def structure_answer(_conversation, answer, _message_id, session_id):
        return {**answer, "session_id": session_id}

    async def thread_pool_exec(function, *args, **kwargs):
        return function(*args, **kwargs)

    modules = {
        "api": ModuleType("api"),
        "api.db": ModuleType("api.db"),
        "api.db.joint_services": ModuleType("api.db.joint_services"),
        "api.db.services": ModuleType("api.db.services"),
        "common": ModuleType("common"),
    }
    for name, value in modules.items():
        value.__path__ = []
        monkeypatch.setitem(sys.modules, name, value)

    model_module = ModuleType("api.db.joint_services.tenant_model_service")
    model_module.resolve_model_config = lambda **_kwargs: {}
    model_module.get_tenant_default_model_by_type = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, model_module.__name__, model_module)
    conversation_module = ModuleType("api.db.services.conversation_service")
    conversation_module.ConversationService = ConversationService
    conversation_module.structure_answer = structure_answer
    monkeypatch.setitem(sys.modules, conversation_module.__name__, conversation_module)
    dialog_module = ModuleType("api.db.services.dialog_service")
    dialog_module.DialogService = DialogService
    dialog_module.rag_agent = rag_agent
    monkeypatch.setitem(sys.modules, dialog_module.__name__, dialog_module)
    kb_module = ModuleType("api.db.services.knowledgebase_service")
    kb_module.KnowledgebaseService = KnowledgebaseService
    kb_module.validate_dataset_embedding_models = lambda _kbs: None
    monkeypatch.setitem(sys.modules, kb_module.__name__, kb_module)
    constants_module = ModuleType("common.constants")
    constants_module.LLMType = SimpleNamespace(CHAT="chat")
    constants_module.StatusEnum = SimpleNamespace(VALID=SimpleNamespace(value="1"))
    monkeypatch.setitem(sys.modules, constants_module.__name__, constants_module)
    misc_module = ModuleType("common.misc_utils")
    misc_module.get_uuid = lambda: "generated-id"
    misc_module.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, misc_module.__name__, misc_module)

    result = asyncio.run(
        MODULE.execute_agentic_search(
            tenant_id="tenant-1",
            options={
                "query": "question",
                "chat_id": "chat-1",
                "session_id": "session-1",
                "dataset_ids": ["request-kb"],
                "model": "request-model",
                "reasoning": 3,
            },
        )
    )

    assert source.kb_ids == ["stored-kb"]
    assert source.llm_id == "stored-model"
    assert captured["dialog"].kb_ids == ["request-kb"]
    assert captured["dialog"].llm_id == "request-model"
    assert result["answer"] == "done"
    assert result["reference_count"] == 1


def test_execute_stateless_search_uses_default_model_without_persistence(monkeypatch):
    captured = {"default_model_calls": 0, "persistence_calls": 0}

    class DialogService:
        @staticmethod
        def query(**_kwargs):
            raise AssertionError("stateless search must not query a chat assistant")

    class ConversationService:
        @staticmethod
        def save(**_kwargs):
            captured["persistence_calls"] += 1

        @staticmethod
        def update_by_id(*_args):
            captured["persistence_calls"] += 1

    class KnowledgebaseService:
        @staticmethod
        def accessible(**_kwargs):
            return True

        @staticmethod
        def query(**_kwargs):
            return [SimpleNamespace(chunk_num=1, embd_id="embedding-1")]

    def get_tenant_default_model_by_type(_tenant_id, _model_type):
        captured["default_model_calls"] += 1
        return {"llm_name": "default-model", "llm_factory": "Provider"}

    async def rag_agent(dialog, messages, _stream, **kwargs):
        captured["dialog"] = dialog
        captured["messages"] = messages
        captured["session_id"] = kwargs.get("session_id")
        yield {
            "answer": "stateless answer",
            "reference": {"chunks": [{"id": "chunk-1", "kb_id": "kb-1", "docnm_kwd": "manual.pdf"}]},
        }

    def structure_answer(_conversation, answer, _message_id, session_id):
        return {**answer, "session_id": session_id}

    async def thread_pool_exec(function, *args, **kwargs):
        return function(*args, **kwargs)

    modules = {
        "api": ModuleType("api"),
        "api.db": ModuleType("api.db"),
        "api.db.joint_services": ModuleType("api.db.joint_services"),
        "api.db.services": ModuleType("api.db.services"),
        "common": ModuleType("common"),
    }
    for name, value in modules.items():
        value.__path__ = []
        monkeypatch.setitem(sys.modules, name, value)

    model_module = ModuleType("api.db.joint_services.tenant_model_service")
    model_module.resolve_model_config = lambda **_kwargs: {}
    model_module.get_tenant_default_model_by_type = get_tenant_default_model_by_type
    monkeypatch.setitem(sys.modules, model_module.__name__, model_module)
    conversation_module = ModuleType("api.db.services.conversation_service")
    conversation_module.ConversationService = ConversationService
    conversation_module.structure_answer = structure_answer
    monkeypatch.setitem(sys.modules, conversation_module.__name__, conversation_module)
    dialog_module = ModuleType("api.db.services.dialog_service")
    dialog_module.DialogService = DialogService
    dialog_module.rag_agent = rag_agent
    monkeypatch.setitem(sys.modules, dialog_module.__name__, dialog_module)
    kb_module = ModuleType("api.db.services.knowledgebase_service")
    kb_module.KnowledgebaseService = KnowledgebaseService
    kb_module.validate_dataset_embedding_models = lambda _kbs: None
    monkeypatch.setitem(sys.modules, kb_module.__name__, kb_module)
    constants_module = ModuleType("common.constants")
    constants_module.LLMType = SimpleNamespace(CHAT="chat")
    constants_module.StatusEnum = SimpleNamespace(VALID=SimpleNamespace(value="1"))
    monkeypatch.setitem(sys.modules, constants_module.__name__, constants_module)
    misc_module = ModuleType("common.misc_utils")
    misc_module.get_uuid = lambda: "generated-id"
    misc_module.thread_pool_exec = thread_pool_exec
    monkeypatch.setitem(sys.modules, misc_module.__name__, misc_module)

    result = asyncio.run(
        MODULE.execute_agentic_search(
            tenant_id="tenant-1",
            options={"query": "question", "dataset_ids": ["kb-1"], "reasoning": 3},
        )
    )

    assert captured["default_model_calls"] == 1
    assert captured["persistence_calls"] == 0
    assert captured["dialog"].kb_ids == ["kb-1"]
    assert captured["dialog"].llm_id == ""
    assert captured["session_id"] is None
    assert result["chat_id"] is None
    assert result["session_id"] is None
    assert result["model"] == "default-model@Provider"
    assert result["reference_count"] == 1
