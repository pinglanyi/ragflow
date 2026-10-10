import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_agentic_graph(monkeypatch):
    advanced_rag_package = ModuleType("rag.advanced_rag")
    advanced_rag_package.__path__ = [str(Path.cwd() / "rag" / "advanced_rag")]
    monkeypatch.setitem(sys.modules, "rag.advanced_rag", advanced_rag_package)

    graph_module = ModuleType("langgraph.graph")
    graph_module.END = "END"
    graph_module.START = "START"
    graph_module.StateGraph = object
    message_module = ModuleType("langgraph.graph.message")
    message_module.add_messages = lambda left, right: right
    monkeypatch.setitem(sys.modules, "langgraph", ModuleType("langgraph"))
    monkeypatch.setitem(sys.modules, "langgraph.graph", graph_module)
    monkeypatch.setitem(sys.modules, "langgraph.graph.message", message_module)

    config_module = ModuleType("rag.advanced_rag.harness.config")
    config_module.NAIVE = SimpleNamespace(agentic=False)
    config_module.THINKING_MODES = {}
    config_module.get_mode = lambda _label: config_module.NAIVE
    config_module.resolve_mode = lambda _tools: SimpleNamespace(sca_max_rounds=0)
    monkeypatch.setitem(sys.modules, "rag.advanced_rag.harness.config", config_module)

    stats_module = ModuleType("rag.advanced_rag.harness.stats")
    stats_module.in_phase = lambda _name: (lambda function: function)
    monkeypatch.setitem(sys.modules, "rag.advanced_rag.harness.stats", stats_module)

    generator_module = ModuleType("rag.prompts.generator")
    generator_module.form_message = lambda system, user: [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    generator_module.kb_prompt = lambda infos, _budget: [
        chunk["content_with_weight"] for chunk in infos["chunks"]
    ]
    generator_module.message_fit_in = lambda messages, _budget: (0, messages)
    generator_module.citation_prompt = lambda _prompts: ""
    monkeypatch.setitem(sys.modules, "rag.prompts.generator", generator_module)

    agentic_module = ModuleType("rag.advanced_rag.agentic_rag")
    agentic_module._EVIDENCE_BUDGET_TOKENS = 4096
    monkeypatch.setitem(sys.modules, "rag.advanced_rag.agentic_rag", agentic_module)

    search_module = ModuleType("rag.advanced_rag.harness.tools.search")
    search_module._chunk_id = lambda chunk: str(chunk.get("chunk_id") or chunk.get("id") or "")
    search_module._is_table_chunk = lambda _chunk: False
    monkeypatch.setitem(sys.modules, "rag.advanced_rag.harness.tools.search", search_module)

    report_module = ModuleType("rag.advanced_rag.harness.prompts.report_prompt")
    report_module.FINAL_ANSWER_SYSTEM = "{cite_rules}"
    report_module.PARTIAL_ANSWER_PREAMBLE = "Partial answer"
    monkeypatch.setitem(sys.modules, "rag.advanced_rag.harness.prompts.report_prompt", report_module)

    path = Path.cwd() / "rag" / "advanced_rag" / "agentic_rag_graph.py"
    spec = importlib.util.spec_from_file_location("_agentic_rag_graph_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ChatModel:
    max_length = 8192

    async def async_chat_streamly_delta(self, _system, _messages, _config):
        yield "破模是在开模初始阶段分开动定模分型面的动作。[ID:0]"


def test_compose_uses_present_evidence_even_when_empty_marker_is_stale(monkeypatch):
    module = _load_agentic_graph(monkeypatch)
    queue = asyncio.Queue()
    tools = SimpleNamespace(
        chat_mdl=_ChatModel(),
        empty_response="EMPTY",
        user_defined_prompts={},
        system_prompt="",
        kbinfos={},
    )
    state = {
        "question": "什么是破模？",
        "empty_result": True,
        "kbinfos": {
            "chunks": [
                {
                    "chunk_id": "0c4c6d974c211637",
                    "doc_id": "484eaa2454bc11f1bbbfb34f79bfd60c",
                    "docnm_kwd": "GB/T 37662.2—2019.pdf",
                    "content_with_weight": "破模：开模初始阶段，使动定模分型面分开的动作。",
                    "similarity": 0.9,
                }
            ],
            "doc_aggs": [],
            "pre_summary": "破模是在开模初始阶段分开动定模分型面的动作。",
        },
    }

    asyncio.run(module._compose_answer_from_evidence(state, tools, queue, {"temperature": 0.3}))

    assert queue.get_nowait() != "EMPTY"
