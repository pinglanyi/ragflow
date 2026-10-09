"""Check model routing without importing optional provider SDKs."""

import ast
import json
import logging
import os
from enum import StrEnum
from pathlib import Path

import pytest


def load_routing_model():
    root = Path(__file__).resolve().parents[4]
    namespace = {"StrEnum": StrEnum, "os": os, "json": json, "JSONDecodeError": json.JSONDecodeError, "logger": logging.getLogger(__name__)}
    definitions = ast.parse((root / "rag/llm/__init__.py").read_text(encoding="utf-8"))
    names = {"SupportedLiteLLMProvider", "FACTORY_DEFAULT_BASE_URL", "LITELLM_PROVIDER_PREFIX"}
    nodes = [node for node in definitions.body if getattr(node, "name", None) in names or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "provider_constants", "exec"), namespace)  # noqa: S102 - trusted repository source
    source = ast.parse((root / "rag/llm/chat_model.py").read_text(encoding="utf-8"))
    model = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "LiteLLMBase")
    model.bases = []
    model.body = [node for node in model.body if isinstance(node, ast.FunctionDef) and node.name in {"__init__", "_is_dashscope_family_provider", "_targets_openai_compatible_endpoint"}]
    exec(compile(ast.Module(body=[model], type_ignores=[]), "routing_model", "exec"), namespace)  # noqa: S102 - trusted repository source
    return namespace["LiteLLMBase"]


@pytest.mark.parametrize("provider", ["Tongyi-Qianwen", "Dashscope"])
@pytest.mark.parametrize("base_url", [None, "https://dashscope.aliyuncs.com/compatible-mode/v1/"])
def test_compatible_endpoint_routes_unknown_model_via_openai(provider, base_url):
    model = load_routing_model()("test-key", "qwen3.6-35b-a3b", base_url, provider=provider)
    assert model.model_name == "openai/qwen3.6-35b-a3b"
    assert model.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


@pytest.mark.parametrize(
    "provider,base_url,expected",
    [
        ("Tongyi-Qianwen", "https://dashscope.aliyuncs.com/api/v1", "dashscope/qwen3.6-35b-a3b"),
        ("DeepSeek", "https://example.test/compatible-mode/v1", "deepseek/qwen3.6-35b-a3b"),
    ],
)
def test_other_routes_preserve_provider(provider, base_url, expected):
    model = load_routing_model()("test-key", "qwen3.6-35b-a3b", base_url, provider=provider)
    assert model.model_name == expected
    assert model.base_url == base_url
