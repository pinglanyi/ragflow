"""The standalone API must enter the research graph even if a model skips tools."""

import ast
import asyncio
import logging
import re
import sys
import time
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def _load_rag_agent(namespace):
    source = (ROOT / "api/db/services/dialog_service.py").read_text(encoding="utf-8")
    node = next(
        item for item in ast.parse(source).body
        if isinstance(item, ast.AsyncFunctionDef) and item.name == "rag_agent"
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<rag_agent>", "exec"), namespace)
    return namespace["rag_agent"]


def _load_stream_parser(namespace):
    source = (ROOT / "api/db/services/dialog_service.py").read_text(encoding="utf-8")
    nodes = [
        item for item in ast.parse(source).body
        if getattr(item, "name", None) in {"_ThinkStreamState", "_stream_with_think_delta"}
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<stream_parser>", "exec"), namespace)
    return namespace["_stream_with_think_delta"]


def _load_agentic_citation_parser(namespace):
    source = (ROOT / "api/db/services/dialog_service.py").read_text(encoding="utf-8")
    node = next(
        item for item in ast.parse(source).body
        if getattr(item, "name", None) == "repair_agentic_citation_formats"
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<agentic_citations>", "exec"), namespace)
    return namespace["repair_agentic_citation_formats"]


def test_agentic_citations_are_one_based_and_accept_the_last_pool_entry():
    repair = _load_agentic_citation_parser(
        {
            "BAD_CITATION_PATTERNS": [re.compile(r"\(\s*ID\s*[: ]*\s*(\d+)\s*\)")],
            "CITATION_MARKER_PATTERN": re.compile(r"\[(?:ID:)?(\d+)\]"),
            "normalize_arabic_digits": lambda answer: answer,
        }
    )

    answer, indices = repair("答案 (ID: 2)", {"chunks": [{"id": "a"}, {"id": "b"}]})

    assert answer == "答案 [ID:2]"
    assert indices == {1}


def test_forced_agentic_search_runs_graph_when_chat_model_skips_tools(monkeypatch):
    called = []
    for name in ("rag", "rag.advanced_rag", "rag.advanced_rag.harness"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    config = ModuleType("rag.advanced_rag.harness.config")
    config.THINKING_MODES = {"low": {}, "medium": {}, "high": {}, "ultra": {}}
    monkeypatch.setitem(sys.modules, config.__name__, config)
    graph = ModuleType("rag.advanced_rag.agentic_rag_graph")

    async def run_agentic_rag(tools, messages, *, gen_conf):
        called.append(messages)
        tools.kbinfos = {
            "chunks": [{"id": "chunk-1", "doc_id": "doc-1", "content_with_weight": "CAN2 接扩展模块"}],
            "doc_aggs": [{"doc_id": "doc-1", "doc_name": "CAN规范.pdf"}],
        }
        yield "扩展模块接 CAN2。[ID:1]"

    graph.run_agentic_rag = run_agentic_rag
    monkeypatch.setitem(sys.modules, graph.__name__, graph)

    class Model:
        mdl = None
        is_tools = True
        model_config = {"model_type": "chat", "llm_factory": ""}

        def bind_tools(self, *_args):
            pass

        async def async_chat(self, *_args):
            return "I do not have enough information."

    class Tools:
        def __init__(self, *_args, **_kwargs):
            self.kbinfos = {
                "chunks": [{"id": "chunk-1", "doc_id": "doc-1", "content_with_weight": "CAN2 接扩展模块"}],
                "doc_aggs": [{"doc_id": "doc-1", "doc_name": "CAN规范.pdf"}],
            }
            self.tools = []

        def sys_prompt(self):
            return "Use retrieval."

    model = Model()
    namespace = {
        "logging": logging,
        "time": time,
        "deepcopy": deepcopy,
        "get_models": lambda _dialog: ([SimpleNamespace(tenant_id="tenant-1")], None, None, model, None),
        "message_has_image_attachments": lambda _message: False,
        "dialog_model_vision_capable": lambda _dialog: False,
        "get_files_content": lambda *_args: ("", [], []),
        "LLM_MESSAGE_FIELDS": {"role", "content"},
        "_should_use_web_search": lambda *_args: False,
        "has_web_search_provider": lambda _config: False,
        "_bound_dataset_names": lambda _dialog: "",
        "_render_reasoning_system_prompt": lambda *_args: "",
        "RAGTools": Tools,
        "normalize_arabic_digits": lambda answer: answer,
        "CITATION_MARKER_PATTERN": re.compile(r"\[(?:ID:)?(\d+)\]"),
        "repair_bad_citation_formats": lambda answer, _refs, indices: (answer, indices),
        "repair_agentic_citation_formats": lambda answer, refs: (
            answer,
            {
                int(match.group(1)) - 1
                for match in re.finditer(r"\[ID:(\d+)\]", answer)
                if 1 <= int(match.group(1)) <= len(refs["chunks"])
            },
        ),
        "_extract_visible_answer": lambda answer: answer,
        "tts": lambda *_args: None,
    }
    rag_agent = _load_rag_agent(namespace)
    dialog = SimpleNamespace(
        prompt_config={"reasoning": 0}, kb_ids=["kb-1"], llm_setting={},
        meta_data_filter=None, similarity_threshold=0.1, vector_similarity_weight=0.3,
        top_n=6, rerank_candidates_count=64, top_k=1024,
    )

    async def run():
        return [
            answer async for answer in rag_agent(
                dialog, [
                    {"role": "user", "content": "我在安装扩展模块"},
                    {"role": "assistant", "content": "请问具体问题？"},
                    {"role": "user", "content": "CAN如何接线？"},
                ],
                False, reasoning=3, force_rag=True,
            )
        ]

    result = asyncio.run(run())
    assert len(called) == 1
    assert [message["role"] for message in called[0]] == ["user", "assistant", "user"]
    assert result[0]["answer"] == "扩展模块接 CAN2。[ID:1]"
    assert result[0]["reference"]["chunks"][0]["id"] == "chunk-1"


def test_forced_stream_runs_graph_and_emits_cited_final(monkeypatch):
    calls = []
    for name in ("rag", "rag.advanced_rag", "rag.advanced_rag.harness"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    config = ModuleType("rag.advanced_rag.harness.config")
    config.THINKING_MODES = {"low": {}, "medium": {}, "high": {}, "ultra": {}}
    monkeypatch.setitem(sys.modules, config.__name__, config)
    graph = ModuleType("rag.advanced_rag.agentic_rag_graph")

    async def run_agentic_rag(tools, messages, *, gen_conf):
        calls.append((messages[-1]["content"], gen_conf))
        tools.kbinfos = {
            "chunks": [{"id": "chunk-1", "doc_id": "doc-1", "content_with_weight": "CAN2 接扩展模块"}],
            "doc_aggs": [{"doc_id": "doc-1", "doc_name": "CAN规范.pdf"}],
        }
        yield "a"
        yield "and[ID:1]"

    graph.run_agentic_rag = run_agentic_rag
    monkeypatch.setitem(sys.modules, graph.__name__, graph)
    think_log = ModuleType("rag.advanced_rag.think_log")
    think_log.install_think_log_handler = lambda: None
    think_log.set_think_log_sink = lambda _sink: object()
    think_log.reset_think_log_sink = lambda _token: None
    monkeypatch.setitem(sys.modules, think_log.__name__, think_log)

    class Model:
        mdl = None
        is_tools = True
        model_config = {"model_type": "chat", "llm_factory": ""}

        def bind_tools(self, *_args):
            pass

        async def async_chat_streamly_delta(self, *_args):
            raise AssertionError("outer chat model must not replace the research graph")
            yield  # pragma: no cover

    class Tools:
        def __init__(self, *_args, **_kwargs):
            self.kbinfos = {"chunks": [], "doc_aggs": []}
            self.tools = []

        def sys_prompt(self):
            return "Use retrieval."

    namespace = {
        "asyncio": asyncio,
        "logging": logging,
        "time": time,
        "deepcopy": deepcopy,
        "get_models": lambda _dialog: ([SimpleNamespace(tenant_id="tenant-1")], None, None, Model(), None),
        "message_has_image_attachments": lambda _message: False,
        "dialog_model_vision_capable": lambda _dialog: False,
        "get_files_content": lambda *_args: ("", [], []),
        "LLM_MESSAGE_FIELDS": {"role", "content"},
        "_should_use_web_search": lambda *_args: False,
        "has_web_search_provider": lambda _config: False,
        "_bound_dataset_names": lambda _dialog: "",
        "_render_reasoning_system_prompt": lambda *_args: "",
        "RAGTools": Tools,
        "normalize_arabic_digits": lambda answer: answer,
        "CITATION_MARKER_PATTERN": re.compile(r"\[(?:ID:)?(\d+)\]"),
        "repair_bad_citation_formats": lambda answer, _refs, indices: (answer, indices),
        "repair_agentic_citation_formats": lambda answer, refs: (
            answer,
            {
                int(match.group(1)) - 1
                for match in re.finditer(r"\[ID:(\d+)\]", answer)
                if 1 <= int(match.group(1)) <= len(refs["chunks"])
            },
        ),
        "re": re,
        "num_tokens_from_string": lambda text: len(text) * 16,
        "_extract_visible_answer": lambda answer: answer,
        "tts": lambda *_args: None,
    }
    _load_stream_parser(namespace)
    rag_agent = _load_rag_agent(namespace)
    dialog = SimpleNamespace(
        prompt_config={"reasoning": 0}, kb_ids=["kb-1"], llm_setting={"temperature": 0},
        meta_data_filter=None, similarity_threshold=0.1, vector_similarity_weight=0.3,
        top_n=6, rerank_candidates_count=64, top_k=1024,
    )

    async def run():
        return [answer async for answer in rag_agent(
            dialog, [{"role": "user", "content": "CAN如何接线？"}], True, reasoning=3, force_rag=True,
        )]

    result = asyncio.run(run())
    assert calls == [("CAN如何接线？", {"temperature": 0})]
    assert "".join(part["answer"] for part in result if not part["final"]) == "aand[ID:1]"
    # rag_agent streams visible text as deltas; its terminal event carries the
    # references.  The HTTP service assembles the final visible answer.
    assert result[-1]["answer"] == ""
    assert result[-1]["reference"]["chunks"][0]["id"] == "chunk-1"
