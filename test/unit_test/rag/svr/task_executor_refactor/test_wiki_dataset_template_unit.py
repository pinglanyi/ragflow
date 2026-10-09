"""Dataset template settings apply to documents uploaded before selection."""
# ruff: noqa: S102 -- execute trusted repository AST
import ast
import asyncio
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


def test_wiki_task_uses_kb_config_when_sample_document_has_no_template():
    root = Path(__file__).resolve().parents[5]
    source = ast.parse((root / "rag/svr/task_executor_refactor/dataset_wiki_generator.py").read_text(encoding="utf-8"))
    run = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_wiki_incremental")
    assignment = next(n for n in run.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "eligible" for t in n.targets))
    captured = {}
    def eligible(docs, tenant, **kwargs):
        captured.update(kwargs)
        return []
    ctx = SimpleNamespace(tenant_id="tenant", parser_config={"chunk_token_num": 512}, kb_parser_config={"compilation_template_group_id": ["custom-wiki"]})
    ns = {"ctx": ctx, "all_docs": [], "deleted_doc_ids": set(), "_wiki_eligible_docs": eligible}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), "wiki_task_config", "exec"), ns)
    assert captured["dataset_parser_config"]["compilation_template_group_id"] == ["custom-wiki"]


def test_document_compile_inherits_dataset_templates_and_keeps_document_override():
    root = Path(__file__).resolve().parents[5]
    source = ast.parse((root / "rag/svr/task_executor_refactor/chunk_post_processor.py").read_text(encoding="utf-8"))
    run = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_document_structure_compile")
    start = next(i for i, n in enumerate(run.body) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ctx" for t in n.targets))
    end = next(i for i, n in enumerate(run.body) if isinstance(n, ast.If))
    wrapper = ast.parse("async def load_ids(handler):\n    pass").body[0]
    wrapper.body = run.body[start:end] + [ast.Return(value=ast.Name(id="template_ids", ctx=ast.Load()))]
    ast.fix_missing_locations(wrapper)
    ns = {
        "DocumentService": SimpleNamespace(get_by_id=lambda doc: (False, None)),
        "_parser_config_compilation_template_ids": lambda pc, tenant: pc.get("compilation_template_group_id", []),
    }
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), "compile_task_config", "exec"), ns)
    for doc_config, expected in [({}, ["dataset-tree"]), ({"compilation_template_group_id": ["document-tree"]}, ["document-tree"])]:
        ctx = SimpleNamespace(doc_id="doc", tenant_id="tenant", parser_config=doc_config, kb_parser_config={"compilation_template_group_id": ["dataset-tree"]})
        assert asyncio.run(ns["load_ids"](SimpleNamespace(_task_context=ctx))) == expected
