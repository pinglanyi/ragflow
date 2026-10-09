"""Document selection must not depend on embedding availability or widen scope."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("metadata_selector_under_test", ROOT / "rag/advanced_rag/harness/tools/metadata.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def services(monkeypatch):
    state = SimpleNamespace(ids=["a", "b"], fields=["year", "model"], documents=[
        {"id": "a", "kb_id": "kb", "name": "A.pdf"},
        {"id": "b", "kb_id": "kb", "name": "B.pdf"},
    ], meta={"a": {"year": "2026"}, "b": {"year": "2026"}}, calls=[], failure=False)

    class Metadata:
        @staticmethod
        def get_metadata_keys_by_kbs(kbs, *, strict=False):
            assert strict
            if state.failure:
                raise RuntimeError("index unavailable")
            return state.fields

        @staticmethod
        def filter_doc_ids_by_meta_pushdown(kbs, filters, logic, limit=10000):
            state.calls.append((kbs, filters, logic))
            return state.ids

        @staticmethod
        def get_metadata_for_documents(ids, kb, *, strict=False):
            assert strict and ids
            return {doc: state.meta[doc] for doc in ids if doc in state.meta}

        @staticmethod
        def get_flatted_meta_by_kbs(kbs, *, strict=False):
            assert strict
            return {"year": {"2026": ["a"], "2025": ["b"]}}

    class Documents:
        @staticmethod
        def get_name_retrieval_documents(kbs, ids):
            return [doc for doc in state.documents if doc["id"] in ids and doc["kb_id"] in kbs]

    async def pool(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    for name, attrs in {
        "api.db.services.doc_metadata_service": {"DocMetadataService": Metadata},
        "api.db.services.document_service": {"DocumentService": Documents},
        "common.misc_utils": {"thread_pool_exec": pool},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    return state


def select(**kwargs):
    return asyncio.run(MODULE.select_metadata_documents(["kb"], [{"key": "year", "op": "=", "value": "2026"}], **kwargs))


def test_metadata_only_returns_documents_and_their_own_values(services):
    result = select()
    assert result["doc_ids"] == ["a", "b"]
    assert result["documents"][0] == {"doc_id": "a", "dataset_id": "kb", "name": "A.pdf", "metadata": {"year": "2026"}}
    assert result["truncated"] is False


def test_selector_intersects_session_scope(services):
    assert select(doc_scope=["b"])["doc_ids"] == ["b"]
    assert select(doc_scope=[])["doc_ids"] == []


def test_stale_or_other_dataset_hits_are_removed(services):
    services.ids = ["a", "stale", "other"]
    services.documents.append({"id": "other", "kb_id": "secret", "name": "Secret.pdf"})
    assert select()["doc_ids"] == ["a"]


def test_invalid_index_ids_are_not_coerced(services):
    services.ids = [12]
    with pytest.raises(RuntimeError, match="document ID"):
        select()


def test_no_match_never_reads_all_metadata(services):
    services.ids = []
    result = select()
    assert result["doc_ids"] == []
    assert result["reason"] == "no_match"


def test_unknown_field_gives_available_fields_without_search(services):
    services.fields = ["model"]
    result = select()
    assert result["reason"] == "unknown_field"
    assert result["available_fields"] == ["model"]
    assert services.calls == []


def test_missing_metadata_differs_from_infrastructure_failure(services):
    services.fields = []
    assert select()["reason"] == "no_metadata"
    services.failure = True
    with pytest.raises(RuntimeError, match="unavailable"):
        select()


def test_result_cap_is_explicit(services):
    result = select(limit=1)
    assert result["doc_ids"] == ["a"]
    assert result["truncated"] is True
    assert "total" not in result


def test_pushdown_fallback_uses_real_metadata_filter(services):
    services.ids = None
    assert select()["doc_ids"] == ["a"]


@pytest.mark.parametrize("op,value", [("=", 2026), ("in", [2026]), ("not in", [2025])])
def test_numeric_values_match_flattened_metadata_in_fallback(services, op, value):
    services.ids = None
    result = asyncio.run(MODULE.select_metadata_documents(["kb"], [{"key": "year", "op": op, "value": value}]))
    assert result["doc_ids"] == ["a"]


def test_multiple_dataset_tenants_are_queried_separately(services):
    services.documents.append({"id": "c", "kb_id": "kb2", "name": "C.pdf"})
    services.ids = ["a", "b", "c"]
    services.meta["c"] = {"year": "2026"}
    result = asyncio.run(MODULE.select_metadata_documents(["kb", "kb2"], [{"key": "year", "op": "=", "value": "2026"}]))
    assert result["doc_ids"] == ["a", "b", "c"]
    assert [call[0] for call in services.calls] == [["kb"], ["kb2"]]


def test_filter_payload_itself_is_bounded():
    with pytest.raises(ValueError, match="8000"):
        MODULE.validate_metadata_filters([{"key": "x", "op": "in", "value": ["y" * 2000] * 10}])


def test_output_size_is_bounded_and_json_safe(services):
    import json

    services.meta["a"] = {"year": "2026", "large": "测" * 70000}
    result = select()
    assert len(json.dumps(result, ensure_ascii=False)) <= 60000
    assert result["truncated"] is True


@pytest.mark.parametrize("filters,logic", [([], "and"), ([{}], "and"),
    ([{"key": "year", "op": "contains", "value": ["2026"]}], "and"),
    ([{"key": "year", "op": "in", "value": "2026"}], "and"),
    ([{"key": "year", "op": "bogus", "value": "2026"}], "and"),
    ([{"key": "year", "op": "=", "value": "2026"}] * 11, "and"),
    ([{"key": "year", "op": "=", "value": "2026"}], "xor")])
def test_filter_validation_rejects_ambiguous_contracts(filters, logic):
    with pytest.raises(ValueError):
        MODULE.validate_metadata_filters(filters, logic)


def test_all_supported_scalar_and_list_operators_validate():
    for op in ("=", "contains", "not contains", "start with", "end with"):
        assert MODULE.validate_metadata_filters([{"key": "型号", "op": op, "value": " X1 "}], "and")[0]["value"] == " X1 "
    for op in ("in", "not in"):
        assert MODULE.validate_metadata_filters([{"key": "year", "op": op, "value": ["2025", "2026"]}], "or")
    for op in ("empty", "not empty"):
        assert MODULE.validate_metadata_filters([{"key": "year", "op": op}], "and")


@pytest.mark.parametrize("method,args,empty", [
    ("get_metadata_keys_by_kbs", (["kb"],), []),
    ("get_metadata_for_documents", (["a"], "kb"), {}),
    ("get_flatted_meta_by_kbs", (["kb"],), {}),
])
def test_real_metadata_reads_preserve_old_default_but_propagate_strict_failures(method, args, empty):
    import ast
    import logging

    source = ast.parse((ROOT / "api/db/services/doc_metadata_service.py").read_text(encoding="utf-8"))
    cls_node = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "DocMetadataService")
    node = next(n for n in cls_node.body if isinstance(n, ast.FunctionDef) and n.name == method)
    node.decorator_list = []

    def fail(*args, **kwargs):
        raise RuntimeError("backend offline")

    namespace = {"logging": logging, "Knowledgebase": SimpleNamespace(get_by_id=fail)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "metadata-read", "exec"), namespace)  # noqa: S102 - trusted repository method
    cls = SimpleNamespace(_search_metadata=fail)
    assert namespace[method](cls, *args) == empty
    with pytest.raises(RuntimeError, match="offline"):
        namespace[method](cls, *args, strict=True)
