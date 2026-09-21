import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


class _DummyManager:
    def __init__(self):
        self.routes = []

    def route(self, path, **kwargs):
        self.routes.append((path, kwargs))

        def decorator(func):
            return func

        return decorator


class _AwaitableValue:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _resolve():
            return self.value

        return _resolve().__await__()


def _load_route(monkeypatch, payload, execute_result=None):
    repo_root = Path(__file__).resolve().parents[3]
    manager = _DummyManager()

    apps = ModuleType("api.apps")
    apps.__path__ = [str(repo_root / "api" / "apps")]
    apps.current_user = SimpleNamespace(id="tenant-1")
    apps.login_required = lambda func: func
    monkeypatch.setitem(sys.modules, "api.apps", apps)

    service = ModuleType("api.apps.services.agentic_search_api_service")

    def validate(value):
        if not value.get("query"):
            raise ValueError("query is required")
        return value

    async def execute(**kwargs):
        execute.calls.append(kwargs)
        return execute_result or {"answer": "ok", "references": []}

    execute.calls = []
    service.validate_agentic_search_request = validate
    service.execute_agentic_search = execute
    monkeypatch.setitem(sys.modules, "api.apps.services.agentic_search_api_service", service)

    utils = ModuleType("api.utils.api_utils")
    utils.get_request_json = lambda: _AwaitableValue(payload)
    utils.get_json_result = lambda **kwargs: kwargs
    utils.get_data_error_result = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "api.utils.api_utils", utils)

    constants = ModuleType("common.constants")
    constants.RetCode = SimpleNamespace(EXCEPTION_ERROR=100)
    monkeypatch.setitem(sys.modules, "common.constants", constants)

    module_path = repo_root / "api" / "apps" / "restful_apis" / "agentic_search_api.py"
    spec = importlib.util.spec_from_file_location("agentic_search_route_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    module.manager = manager
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module, manager, execute


def test_route_is_registered_and_delegates_authenticated_tenant(monkeypatch):
    payload = {"query": "hello", "chat_id": "chat-1"}
    module, manager, execute = _load_route(monkeypatch, payload)
    response = asyncio.run(inspect.unwrap(module.agentic_search)())
    assert ("/agentic-search", {"methods": ["POST"]}) in manager.routes
    assert len(execute.calls) == 1
    assert execute.calls[0]["tenant_id"] == "tenant-1"
    assert execute.calls[0]["options"] == payload
    assert execute.calls[0]["request_id"]
    assert response["data"]["answer"] == "ok"


def test_route_returns_argument_error_for_invalid_payload(monkeypatch):
    module, _manager, execute = _load_route(monkeypatch, {"chat_id": "chat-1"})
    response = asyncio.run(inspect.unwrap(module.agentic_search)())
    assert response["message"] == "query is required"
    assert execute.calls == []


def test_route_returns_request_id_when_execution_fails(monkeypatch):
    module, _manager, _execute = _load_route(monkeypatch, {"query": "hello", "chat_id": "chat-1"})

    async def fail(**_kwargs):
        raise RuntimeError("model unavailable")

    module.execute_agentic_search = fail
    response = asyncio.run(inspect.unwrap(module.agentic_search)())
    assert response["code"] == 100
    assert response["data"]["request_id"]
    assert "model unavailable" in response["message"]
