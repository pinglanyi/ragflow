"""Dataset template settings apply to documents uploaded before selection."""
# ruff: noqa: S102 -- execute trusted repository AST
import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_existing_document_uses_dataset_template_without_changing_document(monkeypatch):
    root = Path(__file__).resolve().parents[5]
    tree = ast.parse((root / "rag/svr/task_executor_refactor/dataset_wiki_generator.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_wiki_eligible_docs")
    service = ModuleType("api.db.services.compilation_template_service")
    service.CompilationTemplateService = SimpleNamespace(load_builtins_from_files=lambda: [{"id": "builtin", "kind": "wiki"}])
    chunk_api = ModuleType("api.apps.restful_apis.chunk_api")
    chunk_api._compilation_template_kind = lambda kind: kind
    monkeypatch.setitem(sys.modules, service.__name__, service)
    monkeypatch.setitem(sys.modules, chunk_api.__name__, chunk_api)
    namespace = {
        "_parser_config_compilation_template_ids": lambda pc, tenant: pc.get("compilation_template_group_id", []),
        "_wiki_template": lambda tid, tenant: {"config": {"kind": "wiki"}},
        "_pipeline_compilation_template_ids": lambda *args: [],
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "wiki_eligibility", "exec"), namespace)
    document = {"id": "doc", "status": "1", "parser_config": {"chunk_token_num": 512}}
    result = namespace["_wiki_eligible_docs"]([document], "tenant", dataset_parser_config={"compilation_template_group_id": ["custom-wiki"]})
    assert result[0][1] == "custom-wiki"
    assert document["parser_config"] == {"chunk_token_num": 512}
