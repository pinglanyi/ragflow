"""MCP transport which validates every destination and connects to its checked IP."""

import httpx

from common.ssrf_guard import assert_url_is_safe


class _GuardedMCPTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport=None):
        self._transport = transport if transport is not None else httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        hostname, ip = assert_url_is_safe(str(request.url))
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=ip),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": hostname},
        )
        return await self._transport.handle_async_request(pinned)

    async def aclose(self):
        await self._transport.aclose()


def create_guarded_mcp_client(headers=None, timeout=None, auth=None):
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout if timeout is not None else httpx.Timeout(30, read=300),
        auth=auth,
        follow_redirects=False,
        trust_env=False,
        transport=_GuardedMCPTransport(),
    )
