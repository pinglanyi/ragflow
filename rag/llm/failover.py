"""Opt-in, conversation-scoped failover for the Python chat bundle protocol."""

import inspect
import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)


class _TrackedToolSession:
    def __init__(self, session, activity):
        self.session, self.activity = session, activity

    def __getattr__(self, name):
        value = getattr(self.session, name)
        if name not in ("tool_call", "tool_call_async"):
            return value

        def tracked(*args, **kwargs):
            # Mark before invocation: even a failed tool can have side effects.
            self.activity["calls"] += 1
            return value(*args, **kwargs)

        return tracked


class _ProviderView:
    def __init__(self, owner):
        object.__setattr__(self, "owner", owner)

    def __getattr__(self, name):
        if name == "last_usage":
            return self.owner.last_usage
        return getattr(self.owner.models[self.owner._state["cursor"]].mdl, name)

    def __setattr__(self, name, value):
        if name == "terminal_tools":
            for model in self.owner.models:
                setattr(model.mdl, name, value)
        else:
            setattr(self.owner.models[self.owner._state["cursor"]].mdl, name, value)


class FailoverChatModel:
    def __init__(self, models, *, state=None, tool_activity=None):
        if not models:
            raise ValueError("A primary chat model is required")
        self.models = list(models)
        self._state = state if state is not None else {"cursor": 0, "blocked_until": 0.0}
        self._tool_activity = tool_activity if tool_activity is not None else {"calls": 0}
        self.last_usage = {}
        self.mdl = _ProviderView(self)

    def __getattr__(self, name):
        return getattr(self.models[self._state["cursor"]], name)

    @property
    def max_length(self):
        return min(model.max_length for model in self.models)

    def clone(self):
        return FailoverChatModel([model.clone() for model in self.models], state=self._state, tool_activity=self._tool_activity)

    def bind_tools(self, session, tools):
        if session is None:
            tracked = None
            tools = [self._track_callable(tool) if callable(tool) else tool for tool in tools]
        else:
            tracked = _TrackedToolSession(session, self._tool_activity)
        for model in self.models:
            model.bind_tools(tracked, tools)

    def _track_callable(self, tool):
        if inspect.iscoroutinefunction(tool):
            @wraps(tool)
            async def tracked(*args, **kwargs):
                self._tool_activity["calls"] += 1
                return await tool(*args, **kwargs)
        else:
            @wraps(tool)
            def tracked(*args, **kwargs):
                self._tool_activity["calls"] += 1
                return tool(*args, **kwargs)
        return tracked

    def _collect_usage(self, model):
        usage = getattr(getattr(model, "mdl", None), "last_usage", None)
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                self.last_usage[key] = self.last_usage.get(key, 0) + int(usage.get(key, 0) or 0)

    def close(self):
        for model in self.models:
            model.close()

    def _order(self):
        if time.monotonic() < self._state["blocked_until"]:
            raise RuntimeError("All configured chat models failed; retry after the cooldown")
        cursor = self._state["cursor"]
        return [(cursor + offset) % len(self.models) for offset in range(len(self.models))]

    @staticmethod
    def _settings(gen_conf):
        return {key: value for key, value in (gen_conf or {}).items() if key != "failover_llm_ids"}

    @staticmethod
    def _check_answer(answer):
        if isinstance(answer, str) and answer.lstrip().startswith("**ERROR**"):
            raise RuntimeError("Configured chat model returned a provider error")

    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        last_error = None
        self.last_usage = {}
        for index in self._order():
            tool_calls = self._tool_activity["calls"]
            try:
                answer = await self.models[index].async_chat(system, history, self._settings(gen_conf), **kwargs)
                self._check_answer(answer)
                self._state["cursor"] = index
                return answer
            except Exception as exc:
                if self._tool_activity["calls"] != tool_calls:
                    raise
                last_error = exc
                logger.warning("Chat model failed; trying next configured model (position=%s, error_type=%s)", index, type(exc).__name__)
            finally:
                self._collect_usage(self.models[index])
        self._state["blocked_until"] = time.monotonic() + 30
        raise RuntimeError("All configured chat models failed") from last_error

    async def _stream(self, method, system, history, gen_conf, **kwargs):
        last_error = None
        self.last_usage = {}
        for index in self._order():
            emitted = False
            tool_calls = self._tool_activity["calls"]
            iterator = getattr(self.models[index], method)(system, history, self._settings(gen_conf), **kwargs)
            try:
                async for part in iterator:
                    self._check_answer(part)
                    if part:
                        emitted = True
                    self._state["cursor"] = index
                    yield part
                self._state["cursor"] = index
                return
            except Exception as exc:
                if emitted or self._tool_activity["calls"] != tool_calls:
                    raise
                last_error = exc
                logger.warning("Chat stream failed before content; trying next configured model (position=%s, error_type=%s)", index, type(exc).__name__)
            finally:
                close = getattr(iterator, "aclose", None)
                if close:
                    await close()
                self._collect_usage(self.models[index])
        self._state["blocked_until"] = time.monotonic() + 30
        raise RuntimeError("All configured chat models failed") from last_error

    async def async_chat_streamly(self, system, history, gen_conf=None, **kwargs):
        iterator = self._stream("async_chat_streamly", system, history, gen_conf, **kwargs)
        try:
            async for part in iterator:
                yield part
        finally:
            await iterator.aclose()

    async def async_chat_streamly_delta(self, system, history, gen_conf=None, **kwargs):
        iterator = self._stream("async_chat_streamly_delta", system, history, gen_conf, **kwargs)
        try:
            async for part in iterator:
                yield part
        finally:
            await iterator.aclose()


def configure_chat_failover(primary, settings, resolve, build):
    refs = (settings or {}).get("failover_llm_ids")
    if not refs:
        return primary
    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
        raise ValueError("failover_llm_ids must be a list of model IDs")
    models = [primary]
    configurations = [primary.model_config]
    for ref in dict.fromkeys(ref.strip() for ref in refs if ref.strip()):
        try:
            config = resolve(ref)
            if config in configurations:
                continue
            if config.get("model_type") != primary.model_config.get("model_type"):
                logger.warning("Skipping fallback chat model with incompatible model type")
                continue
            model = build(config)
            if primary.is_tools and not model.is_tools:
                model.close()
                logger.warning("Skipping fallback model without primary model's tool support")
                continue
        except (LookupError, ValueError, RuntimeError):
            logger.warning("Skipping unavailable configured fallback chat model")
            continue
        configurations.append(config)
        models.append(model)
    return FailoverChatModel(models)
