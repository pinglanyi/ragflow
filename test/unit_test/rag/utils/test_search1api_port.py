import ast
import logging
from pathlib import Path
from typing import Protocol

import pytest

ROOT = Path(__file__).resolve().parents[4]


def factory_namespace():
    tree = ast.parse((ROOT / "rag/utils/web_search_conn.py").read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]

    class Provider:
        def __init__(self, key):
            self.api_key = key

    ns = {"logging": logging, "Protocol": Protocol, "Search1API": Provider}
    exec(compile(tree, "web_search_conn", "exec"), ns)  # noqa: S102 - execute trusted local definitions without optional SDKs
    return ns


def test_search1api_selects_trimmed_own_key():
    ns = factory_namespace()
    config = {"web_search_provider": "search1api", "search1api_api_key": " own-key ", "tavily_api_key": "other"}
    assert ns["has_web_search_provider"](config)
    assert ns["create_web_search_provider"](config).api_key == "own-key"


@pytest.mark.parametrize("key", [None, "", "  ", 123])
def test_search1api_requires_its_own_key(key):
    ns = factory_namespace()
    config = {"web_search_provider": "search1api", "search1api_api_key": key, "tavily_api_key": "other"}
    assert not ns["has_web_search_provider"](config)
    assert ns["create_web_search_provider"](config) is None


def connector_namespace(post):
    from types import SimpleNamespace

    path = ROOT / "rag/utils/search1api_conn.py"
    assert path.exists(), "Search1API connector is missing"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]

    class HTTPError(Exception):
        pass

    class RequestException(Exception):
        pass

    ns = {
        "logging": logging,
        "Any": object,
        "requests": SimpleNamespace(post=post, HTTPError=HTTPError, RequestException=RequestException),
        "DEFAULT_TIMEOUT": 30,
        "rag_tokenizer": SimpleNamespace(tokenize=lambda text: text),
        "normalize_web_evidence": lambda result: result,
    }
    exec(compile(tree, "search1api_conn", "exec"), ns)  # noqa: S102 - execute trusted local definitions without optional SDKs
    return ns


def test_search1api_posts_bearer_query_and_filters_before_limit():
    from types import SimpleNamespace

    calls = []
    hits = [{"title": "missing URL", "snippet": "discard"}, {"link": "https://empty", "snippet": " "}] + [{"title": str(i), "link": f"https://result/{i}", "snippet": f" text {i} "} for i in range(8)]

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"results": hits})

    ns = connector_namespace(post)
    payload = ns["Search1API"]("secret").retrieve_chunks("question")
    assert len(payload["chunks"]) == 6
    assert payload["chunks"][0]["content_with_weight"] == "text 0"
    assert payload["chunks"][0]["url"] == "https://result/0"
    assert payload["doc_aggs"][0]["doc_id"] == payload["chunks"][0]["doc_id"]
    assert calls[0][0] == ("https://api.search1api.com/search",)
    assert calls[0][1]["json"] == {"query": "question", "max_results": 6}
    assert calls[0][1]["headers"]["Authorization"] == "Bearer secret"
    assert calls[0][1]["timeout"] == 30


@pytest.mark.parametrize("response", [None, [], {"results": None}, {"results": "bad"}, {"results": [{}, 1]}, {}])
def test_search1api_bad_or_empty_payload_is_safe(response):
    from types import SimpleNamespace

    ns = connector_namespace(lambda *a, **kw: SimpleNamespace(raise_for_status=lambda: None, json=lambda: response))
    assert ns["Search1API"]("secret").retrieve_chunks("query") == {"chunks": [], "doc_aggs": []}


@pytest.mark.parametrize("kind", ["HTTPError", "RequestException"])
def test_search1api_request_failures_return_empty_without_logging_secrets(caplog, kind):
    from types import SimpleNamespace

    ns = connector_namespace(None)
    error = getattr(ns["requests"], kind)("secret-key-in-provider-error")
    if kind == "HTTPError":
        error.response = SimpleNamespace(status_code=401)

    def fail(*args, **kwargs):
        raise error

    ns["requests"].post = fail
    assert ns["Search1API"]("secret").retrieve_chunks("query") == {"chunks": [], "doc_aggs": []}
    assert "secret-key-in-provider-error" not in caplog.text
