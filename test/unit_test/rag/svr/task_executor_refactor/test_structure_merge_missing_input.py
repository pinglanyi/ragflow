"""Missing structure inputs must not be reported as a successful build."""
# ruff: noqa: S102 -- execute trusted repository AST
import ast
import asyncio
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize("task_type", ["structure_graph", "structure_mindmap", "timeline"])
@pytest.mark.parametrize("pairs", [set(), {("graph", "wrong-kind")}])
def test_missing_structure_input_fails_with_actionable_message(monkeypatch, task_type, pairs):
    root = Path(__file__).resolve().parents[5]
    tree = ast.parse((root / "rag/svr/task_executor_refactor/dataset_structure_merger.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_structure_merge")
    services = {
        "api.db.services.compilation_template_service": {"CompilationTemplateService": SimpleNamespace(get_saved=lambda *args: {"kind": "tree"})},
        "api.apps.services.dataset_api_service": {"resolve_model_config": lambda *args: {}},
        "api.db.services.knowledgebase_service": {"KnowledgebaseService": SimpleNamespace(get_by_id=lambda *args: (True, SimpleNamespace(embd_id="embedding")))},
        "api.db.services.llm_service": {"LLMBundle": lambda *args, **kwargs: object()},
        "common.constants": {"LLMType": SimpleNamespace(EMBEDDING=SimpleNamespace(value="embedding"))},
    }
    for name, attrs in services.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    ns = {"TaskContext": object, "logging": logging, "Optional": __import__("typing").Optional,
          "_collect_structure_pairs": AsyncMock(return_value=pairs)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "structure_merge", "exec"), ns)
    progress = []
    ctx = SimpleNamespace(task_type=task_type, tenant_id="tenant", kb_id="kb", language="English", progress_cb=lambda *args: progress.append(args))
    with pytest.raises(RuntimeError, match="(?i)template.*compil"):
        asyncio.run(ns["run_structure_merge"](ctx))
    assert not any(value == 1.0 for value, *_ in progress)
