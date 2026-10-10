"""Exercise real tool and connector definitions without booting databases/SDKs."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from test.unit_test.rag.utils.test_search1api_port import connector_namespace

ROOT = Path(__file__).resolve().parents[4]


def load_tool(post):
    connector = connector_namespace(post)
    connector["urlsplit"] = urlsplit

    class ParamBase:
        def __init__(self):
            self.outputs = {}

    base_tree = ast.parse((ROOT / "agent/tools/base.py").read_text(encoding="utf-8"))
    base_tree.body = [n for n in base_tree.body if isinstance(n, ast.ClassDef) and n.name == "ToolParamBase"]
    from copy import deepcopy

    ns = {"ComponentParamBase": ParamBase, "deepcopy": deepcopy}
    exec(compile(base_tree, "tool_param", "exec"), ns)  # noqa: S102 - trusted local definitions, isolated optional SDKs

    class ToolBase:
        def set_output(self, key, value):
            self.outputs[key] = value

        def output(self, key=None):
            return self.outputs.get(key) if key else self.outputs

        def check_if_canceled(self, *args):
            return self.canceled

    from rag.utils.web_evidence import normalize_web_evidence

    ns.update(
        ToolBase=ToolBase,
        ToolMeta=dict,
        Search1API=connector["Search1API"],
        normalize_web_evidence=normalize_web_evidence,
        kb_prompt=lambda data, *args: [json.dumps(data, ensure_ascii=False)],
    )
    path = ROOT / "agent/tools/search1api.py"
    assert path.exists(), "Python workflow Search1API tools are missing"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, str(path), "exec"), ns)  # noqa: S102 - trusted local definitions, isolated optional SDKs
    return ns, connector


def make_tool(post, crawl=False):
    ns, connector = load_tool(post)
    name = "Search1APICrawl" if crawl else "Search1APISearch"
    tool = ns[name].__new__(ns[name])
    tool._param = ns[name + "Param"]()
    tool._param.api_key = " test-secret "
    tool.outputs = {}
    tool.canceled = False
    tool.references = []
    tool._canvas = SimpleNamespace(add_reference=lambda chunks, aggs: tool.references.append((chunks, aggs)))
    return tool, connector


def capture(payload):
    calls = []

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    return post, calls


def test_search_defaults_outputs_and_stable_references():
    results = [
        {"title": "A", "link": "https://example.com/a", "content": " Page A ", "snippet": "Snippet A"},
        {"title": "B", "link": "https://example.com/b", "content": " ", "snippet": "Snippet B"},
    ]
    post, calls = capture({"results": results})
    tool, _ = make_tool(post)
    first = tool._invoke(query="robot")
    assert tool.outputs["json"] == results
    assert first == tool.outputs["formalized_content"]
    assert calls[0]["url"] == "https://api.search1api.com/search"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-secret"
    assert calls[0]["json"] == {"query": "robot", "max_results": 10, "search_service": "google"}
    assert calls[0]["timeout"]
    assert "RAGFlow" in calls[0]["headers"]["User-Agent"]
    chunks, aggs = tool.references[0]
    assert [c["content"] for c in chunks] == ["Page A", "Snippet B"]
    assert chunks[0]["doc_id"] == aggs[0]["doc_id"]
    tool._invoke(query="robot")
    assert tool.references[1] == tool.references[0]


def test_news_override_drops_incompatible_node_service_and_clamps_count():
    post, calls = capture({"results": [{"snippet": str(i)} for i in range(60)]})
    tool, _ = make_tool(post)
    tool._param.search_service = "github"
    tool._invoke(query="robot", channel=" NEWS ", time_range="day", max_results="90")
    assert calls[0]["url"] == "https://api.search1api.com/news"
    assert calls[0]["json"] == {"query": "robot", "max_results": 50, "time_range": "day"}
    assert len(tool.outputs["json"]) == 50


def test_general_override_drops_news_only_node_default():
    post, calls = capture({"results": []})
    tool, _ = make_tool(post)
    tool._param.channel = "news"
    tool._param.search_service = "reuters"
    tool._invoke(query="robot", channel="general")
    assert calls and calls[0]["url"] == "https://api.search1api.com/search"
    assert "search_service" not in calls[0]["json"]


@pytest.mark.parametrize("args", [{"channel": "invalid"}, {"channel": "news", "search_service": "github"}, {"time_range": "yesterday"}])
def test_invalid_arguments_report_error_without_request(args):
    post, calls = capture({"results": []})
    tool, _ = make_tool(post)
    tool._invoke(query="robot", **args)
    assert not calls
    assert tool.outputs["_ERROR"]


@pytest.mark.parametrize("count,expected", [(None, 10), ("", 10), ("wrong", 10), (0, 1), (-1, 1), ("2", 2)])
def test_result_count_fallback(count, expected):
    post, calls = capture({"results": []})
    tool, _ = make_tool(post)
    tool._invoke(query="robot", max_results=count)
    assert calls[0]["json"]["max_results"] == expected


def test_empty_query_clears_outputs_without_request():
    post, calls = capture({"results": []})
    tool, _ = make_tool(post)
    tool.outputs = {"json": [1], "formalized_content": "old", "_ERROR": "old"}
    assert tool._invoke(query="  ") == ""
    assert not calls
    assert tool.outputs == {"json": [], "formalized_content": "", "_ERROR": ""}


def test_key_is_config_only_and_missing_key_is_error():
    post, calls = capture({"results": []})
    tool, _ = make_tool(post)
    assert "api_key" not in tool._param.get_meta()["function"]["parameters"]["properties"]
    tool._param.api_key = " "
    tool._invoke(query="robot", api_key="model-must-not-override")
    assert not calls
    assert tool.outputs["_ERROR"]


@pytest.mark.parametrize("payload", [None, [], {"results": "bad"}])
def test_bad_search_response_is_error(payload):
    post, _ = capture(payload)
    tool, _ = make_tool(post)
    tool._invoke(query="robot")
    assert tool.outputs["_ERROR"]


def test_provider_error_does_not_expose_key():
    tool, connector = make_tool(None)

    def fail(*args, **kwargs):
        raise connector["requests"].RequestException("test-secret in provider body")

    connector["requests"].post = fail
    result = tool._invoke(query="robot")
    assert "test-secret" not in str(result) + str(tool.outputs)
    assert tool.outputs["_ERROR"]


def test_crawl_preserves_page_object_and_uses_config_url():
    page = {"title": "A", "link": "https://example.com/a", "content": "Body", "metadata": {"author": "A"}}
    post, calls = capture({"results": page})
    tool, _ = make_tool(post, crawl=True)
    tool._param.url = "https://example.com/a"
    assert tool._invoke() == page
    assert tool.outputs["json"] == page
    assert calls[0]["url"] == "https://api.search1api.com/crawl"
    assert calls[0]["json"] == {"url": "https://example.com/a"}
    assert calls[0]["timeout"] == 60
    assert "api_key" not in tool._param.get_meta()["function"]["parameters"]["properties"]


@pytest.mark.parametrize("url", ["", "file:///etc/passwd", "javascript:alert(1)", "/relative", "https://", "https://user:password@example.com"])
def test_crawl_rejects_invalid_url_before_request(url):
    post, calls = capture({"results": {}})
    tool, _ = make_tool(post, crawl=True)
    tool._invoke(url=url)
    assert not calls
    assert tool.outputs["_ERROR"]


@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": []}])
def test_crawl_requires_page_object(payload):
    post, _ = capture(payload)
    tool, _ = make_tool(post, crawl=True)
    tool._invoke(url="https://example.com")
    assert tool.outputs["_ERROR"]


@pytest.mark.parametrize("crawl", [False, True])
def test_canceled_before_request(crawl):
    post, calls = capture({"results": {}})
    tool, _ = make_tool(post, crawl=crawl)
    tool.canceled = True
    assert tool._invoke(query="robot", url="https://example.com") is None
    assert not calls


def test_canceled_after_request_does_not_publish_results():
    post, _ = capture({"results": [{"content": "discard"}]})
    tool, connector = make_tool(post)

    def cancel(*args, **kwargs):
        tool.canceled = True
        return post(*args, **kwargs)

    connector["requests"].post = cancel
    assert tool._invoke(query="robot") is None
    assert tool.outputs["json"] == []
    assert not tool.references
