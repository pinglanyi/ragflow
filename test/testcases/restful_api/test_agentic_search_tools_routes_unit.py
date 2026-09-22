"""Authenticated routing for seven independent Agentic Search tool URLs."""

import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_tool_route_uses_authenticated_user_and_tool_name(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    routes = []
    calls = []
    manager = SimpleNamespace(route=lambda path, **kwargs: lambda fn: routes.append((path, kwargs)) or fn)
    apps = ModuleType("api.apps")
    apps.current_user = SimpleNamespace(id="user-1")
    apps.login_required = lambda fn: fn
    monkeypatch.setitem(sys.modules, "api.apps", apps)
    service = ModuleType("api.apps.services.agentic_search_tools_service")

    async def execute_tool(name, payload, *, user_id):
        calls.append((name, payload, user_id))
        return {"chunks": []}

    service.execute_tool = execute_tool
    monkeypatch.setitem(sys.modules, "api.apps.services.agentic_search_tools_service", service)
    utils = ModuleType("api.utils.api_utils")

    async def request_json():
        return {"query": "CAN"}

    utils.get_request_json = request_json
    utils.get_json_result = lambda **kwargs: kwargs
    utils.get_data_error_result = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "api.utils.api_utils", utils)
    constants = ModuleType("common.constants")
    constants.RetCode = SimpleNamespace(EXCEPTION_ERROR=100)
    monkeypatch.setitem(sys.modules, "common.constants", constants)

    path = root / "api/apps/restful_apis/agentic_search_tools_api.py"
    spec = importlib.util.spec_from_file_location("agentic_search_tools_route_under_test", path)
    module = importlib.util.module_from_spec(spec)
    module.manager = manager
    spec.loader.exec_module(module)
    response = asyncio.run(inspect.unwrap(module.agentic_search_tool)("search"))
    assert ("/agentic-search/tools/<tool_name>", {"methods": ["POST"]}) in routes
    assert calls == [("search", {"query": "CAN"}, "user-1")]
    assert response["data"]["chunks"] == []
    assert response["data"]["request_id"]


def test_document_name_route_uses_authenticated_user(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    manager = SimpleNamespace(route=lambda path, **kwargs: lambda fn: fn)
    apps = ModuleType("api.apps")
    apps.current_user = SimpleNamespace(id="user-1")
    apps.login_required = lambda fn: fn
    monkeypatch.setitem(sys.modules, "api.apps", apps)
    tools = ModuleType("api.apps.services.agentic_search_tools_service")
    tools.execute_tool = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, tools.__name__, tools)
    calls = []
    documents = ModuleType("api.apps.services.agentic_search_document_service")

    async def retrieve(payload, *, user_id):
        calls.append((payload, user_id))
        return {"documents": [], "count": 0}

    documents.retrieve_documents_by_name = retrieve
    monkeypatch.setitem(sys.modules, documents.__name__, documents)
    utils = ModuleType("api.utils.api_utils")

    async def request_json():
        return {"query": "E502"}

    utils.get_request_json = request_json
    utils.get_json_result = lambda **kwargs: kwargs
    utils.get_data_error_result = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "api.utils.api_utils", utils)
    constants = ModuleType("common.constants")
    constants.RetCode = SimpleNamespace(EXCEPTION_ERROR=100)
    monkeypatch.setitem(sys.modules, "common.constants", constants)

    path = root / "api/apps/restful_apis/agentic_search_tools_api.py"
    spec = importlib.util.spec_from_file_location("agentic_search_document_route_under_test", path)
    module = importlib.util.module_from_spec(spec)
    module.manager = manager
    spec.loader.exec_module(module)
    response = asyncio.run(inspect.unwrap(module.agentic_search_tool)("retrieval-doc-name"))
    assert calls == [({"query": "E502"}, "user-1")]
    assert response["data"]["documents"] == []
    assert response["data"]["request_id"]
