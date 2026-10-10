import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest


def load():
    path = Path(__file__).resolve().parents[3] / "common/mcp_http_client.py"
    spec = importlib.util.spec_from_file_location("mcp_http_test_subject", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transport_validates_and_pins_ip_preserving_host_sni_and_original_url(monkeypatch):
    module = load()
    calls = []
    monkeypatch.setattr(module, "assert_url_is_safe", lambda url: ("mcp.example", "93.184.216.34"))

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with httpx.AsyncClient(transport=module._GuardedMCPTransport(httpx.MockTransport(handler))) as client:
            response = await client.post("https://mcp.example:8443/mcp", content=b"body")
            assert str(response.request.url) == "https://mcp.example:8443/mcp"

    asyncio.run(run())
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].headers["host"] == "mcp.example:8443"
    assert calls[0].extensions["sni_hostname"] == "mcp.example"
    assert calls[0].content == b"body"


def test_transport_blocks_new_unsafe_destination_before_sending(monkeypatch):
    module = load()
    calls = []

    def reject(url):
        raise ValueError("non-public address")

    monkeypatch.setattr(module, "assert_url_is_safe", reject)

    async def handler(request):
        calls.append(request)
        return httpx.Response(200)

    async def run():
        async with httpx.AsyncClient(transport=module._GuardedMCPTransport(httpx.MockTransport(handler))) as client:
            await client.get("http://127.0.0.1/mcp")

    with pytest.raises(ValueError, match="non-public"):
        asyncio.run(run())
    assert calls == []


def test_factory_disables_automatic_redirects_and_env_proxy_bypass(monkeypatch):
    module = load()
    options = {}

    def client(**kwargs):
        options.update(kwargs)
        return "client"

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    assert module.create_guarded_mcp_client(headers={"X-Key": "secret"}) == "client"
    assert options["follow_redirects"] is False
    assert options["trust_env"] is False
    assert options["headers"] == {"X-Key": "secret"}
