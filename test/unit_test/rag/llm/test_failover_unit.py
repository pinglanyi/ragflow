import ast
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def load():
    path = Path(__file__).resolve().parents[4] / "rag/llm/failover.py"
    spec = importlib.util.spec_from_file_location("failover_test_subject", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Model:
    def __init__(self, answer="ok", parts=None):
        self.answer, self.parts = answer, parts or []
        self.calls = 0
        self.configs = []
        self.mdl = SimpleNamespace(terminal_tools=set())
        self.model_config = {"llm_name": str(answer), "model_type": "chat"}
        self.max_length = 100
        self.is_tools = True
        self.bound = []
        self.closed = False

    async def async_chat(self, system, history, gen_conf=None, **kw):
        self.calls += 1
        self.configs.append(gen_conf)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    async def async_chat_streamly_delta(self, *args, **kw):
        self.calls += 1
        for part in self.parts:
            if isinstance(part, BaseException):
                raise part
            yield part

    async_chat_streamly = async_chat_streamly_delta

    def bind_tools(self, *args):
        self.bound.append(args)

    def clone(self):
        return Model(self.answer, self.parts)

    def close(self):
        self.closed = True


def test_configured_fallback_is_sticky_and_filters_provider_settings():
    a, b = Model(RuntimeError("unavailable")), Model("answer")
    chain = load().FailoverChatModel([a, b])
    settings = {"temperature": 0.2, "failover_llm_ids": ["backup"]}
    assert asyncio.run(chain.async_chat("sys", [], settings)) == "answer"
    assert asyncio.run(chain.async_chat("sys", [], settings)) == "answer"
    assert (a.calls, b.calls) == (1, 2)
    assert b.configs[-1] == {"temperature": 0.2}
    assert "failover_llm_ids" in settings


def test_provider_error_text_also_fails_over():
    a, b = Model("**ERROR**: rate limit"), Model("answer")
    assert asyncio.run(load().FailoverChatModel([a, b]).async_chat("sys", [])) == "answer"


def test_cancel_is_never_replayed():
    a, b = Model(asyncio.CancelledError()), Model("answer")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(load().FailoverChatModel([a, b]).async_chat("sys", []))
    assert b.calls == 0


def test_tool_execution_is_not_replayed_after_provider_failure():
    class ToolModel(Model):
        async def async_chat(self, *args, **kwargs):
            self.bound[-1][0].tool_call("write", {})
            raise RuntimeError("failed after write")

    session = SimpleNamespace(tool_call=lambda *args: "done")
    primary, backup = ToolModel(), Model("backup")
    chain = load().FailoverChatModel([primary, backup])
    chain.bind_tools(session, ["write"])
    with pytest.raises(RuntimeError, match="failed after write"):
        asyncio.run(chain.async_chat("sys", []))
    assert backup.calls == 0


def test_callable_tools_keep_none_session_and_prevent_replay():
    async def write():
        return "done"

    write._is_tool = True
    write.openai_schema = {"function": {"name": "write"}}

    class ToolModel(Model):
        async def async_chat(self, *args, **kwargs):
            session, tools = self.bound[-1]
            assert session is None
            assert tools[0]._is_tool
            assert tools[0].openai_schema == write.openai_schema
            await tools[0]()
            raise RuntimeError("failed after write")

    primary, backup = ToolModel(), Model("backup")
    chain = load().FailoverChatModel([primary, backup])
    chain.bind_tools(None, [write])
    with pytest.raises(RuntimeError, match="failed after write"):
        asyncio.run(chain.async_chat("sys", []))
    assert backup.calls == 0


def test_usage_includes_failed_and_successful_model_attempts():
    a, b = Model("**ERROR** failed"), Model("answer")
    a.mdl.last_usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    b.mdl.last_usage = {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11}
    chain = load().FailoverChatModel([a, b])
    asyncio.run(chain.async_chat("sys", []))
    assert chain.mdl.last_usage["total_tokens"] == 16


@pytest.mark.parametrize("method", ["async_chat_streamly", "async_chat_streamly_delta"])
def test_closing_outer_stream_closes_provider_immediately(method):
    closed = []

    class StreamingModel(Model):
        async def stream(self, *args, **kwargs):
            try:
                yield "partial"
                yield "rest"
            finally:
                closed.append(True)

        async_chat_streamly = stream
        async_chat_streamly_delta = stream

    async def run():
        stream = getattr(load().FailoverChatModel([StreamingModel()]), method)("sys", [])
        assert await anext(stream) == "partial"
        await stream.aclose()
        assert closed == [True]

    asyncio.run(run())


@pytest.mark.parametrize("method", ["async_chat_streamly", "async_chat_streamly_delta"])
def test_stream_switches_only_before_content(method):
    async def collect(chain):
        return [part async for part in getattr(chain, method)("sys", [])]

    a, b = Model(parts=[RuntimeError("timeout")]), Model(parts=["answer"])
    assert asyncio.run(collect(load().FailoverChatModel([a, b]))) == ["answer"]
    a, b = Model(parts=["partial", RuntimeError("timeout")]), Model(parts=["answer"])
    with pytest.raises(RuntimeError, match="timeout"):
        asyncio.run(collect(load().FailoverChatModel([a, b])))
    assert b.calls == 0


def test_tools_terminal_flags_and_clones_preserve_chain():
    a, b = Model(), Model()
    chain = load().FailoverChatModel([a, b])
    chain.bind_tools("session", ["rag"])
    chain.mdl.terminal_tools = {"rag"}
    assert a.bound == b.bound
    assert a.bound[0][0].session == "session"
    assert a.bound[0][1] == ["rag"]
    assert a.mdl.terminal_tools == b.mdl.terminal_tools == {"rag"}
    clone = chain.clone()
    assert len(clone.models) == 2
    chain.close()
    assert a.closed and b.closed


def test_disabled_configuration_keeps_original_model():
    primary = Model()
    module = load()
    assert module.configure_chat_failover(primary, {}, lambda _: None, lambda _: None) is primary


def test_resolution_deduplicates_and_skips_missing_models():
    module = load()
    primary = Model()
    seen = []

    def resolve(ref):
        seen.append(ref)
        if ref == "missing":
            raise LookupError("missing")
        return {"llm_name": ref, "model_type": "chat"}

    chain = module.configure_chat_failover(primary, {"failover_llm_ids": ["backup", "backup", "missing"]}, resolve, lambda _: Model())
    assert seen == ["backup", "missing"]
    assert len(chain.models) == 2


def test_fallback_cannot_drop_tool_support():
    module = load()
    primary, backup = Model(), Model()
    backup.is_tools = False
    chain = module.configure_chat_failover(primary, {"failover_llm_ids": ["backup"]},
                                           lambda _: {"llm_name": "backup", "model_type": "chat"}, lambda _: backup)
    assert chain.models == [primary]
    assert backup.closed


def test_all_failures_cool_down_without_more_provider_calls():
    module = load()
    a, b = Model(RuntimeError("offline")), Model(RuntimeError("offline"))
    chain = module.FailoverChatModel([a, b])
    with pytest.raises(RuntimeError, match="All configured"):
        asyncio.run(chain.async_chat("sys", []))
    with pytest.raises(RuntimeError, match="cooldown"):
        asyncio.run(chain.async_chat("sys", []))
    assert (a.calls, b.calls) == (1, 1)


def test_dialog_factory_resolves_fallback_in_same_tenant_with_trace_options():
    source = Path(__file__).resolve().parents[4] / "api/db/services/dialog_service.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_with_dialog_failover"), None)
    assert function is not None, "Dialog model construction must connect the failover chain"
    calls = []
    def resolve(tenant, kind, ref):
        calls.append((tenant, kind, ref))
        return {"llm_name": ref, "model_type": "chat"}
    def build(tenant, config, **kw):
        assert tenant == "owner" and kw == {"langfuse_session_id": "session"}
        return Model("backup")
    scope = {"configure_chat_failover": load().configure_chat_failover, "resolve_model_config": resolve, "LLMBundle": build}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), scope)  # noqa: S102 - execute trusted repository definitions in an isolated test scope
    dialog = SimpleNamespace(tenant_id="owner", llm_setting={"failover_llm_ids": ["backup"]})
    chain = scope["_with_dialog_failover"](dialog, Model(), langfuse_session_id="session")
    assert calls == [("owner", "chat", "backup")]
    assert len(chain.models) == 2
