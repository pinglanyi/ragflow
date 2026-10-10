"""Exercise the connectivity probe without external model requests."""

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("content,reasoning,expected", [("OK", None, True), (None, "Model is reasoning", True), (None, None, False)])
def test_probe_accepts_reasoning_model_response(monkeypatch, content, reasoning, expected):
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "api/apps/services/multimodal_api_service.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "test_model")
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, reasoning_content=reasoning))], usage=None)
    client = Mock()
    client.chat.completions.create.return_value = response
    sdk = ModuleType("openai")
    sdk.OpenAI = Mock()
    sdk.OpenAI.return_value.__enter__ = Mock(return_value=client)
    sdk.OpenAI.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setitem(sys.modules, "openai", sdk)
    llm_type = Mock(side_effect=lambda value: value)
    llm_type.CHAT.value = "chat"
    llm_type.VISION.value = "vision"
    llm_type.EMBEDDING.value = "embedding"
    scope = {"LLMType": llm_type, "resolve_model_config": lambda *args: {"api_base": "https://example.test/v1", "llm_name": "reasoning-model"}, "monotonic": lambda: 0, "ApiError": RuntimeError, "logger": Mock()}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<model-probe>", "exec"), scope)  # noqa: S102 - trusted repository function
    assert scope["test_model"]("tenant", "model", "chat")["ok"] is expected
