"""Navigation identity filters must work with both deployed ES mappings."""

import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[5]


def q(kind, **kwargs):
    return {kind: kwargs}


def matches(query, indexed_fields):
    kind, options = next(iter(query.items()))
    if kind == "exists":
        return options["field"] in indexed_fields
    if kind in {"term", "terms"}:
        field, value = next(iter(options.items()))
        values = value if isinstance(value, list) else [value]
        tokens = indexed_fields.get(field, [])
        return any(v in tokens for v in values)
    assert kind == "bool"
    return (all(matches(q, indexed_fields) for q in options.get("filter", []))
            and not any(matches(q, indexed_fields) for q in options.get("must_not", []))
            and sum(matches(q, indexed_fields) for q in options.get("should", []))
            >= options.get("minimum_should_match", 0))


@pytest.mark.parametrize("as_list", [False, True])
@pytest.mark.parametrize("dynamic_text", [False, True])
@pytest.mark.parametrize("parent", ["root", "skill-15-xindong-hmi-specs"])
def test_parent_identity_is_exact_for_both_index_mappings(as_list, dynamic_text, parent):
    path = ROOT / "rag/utils/es_conn.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if getattr(n, "name", None) == "_navigation_parent_filter")
    ns = {"Q": q}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), ns)
    query = ns["_navigation_parent_filter"]([parent] if as_list else parent)

    def indexed(identity):
        if dynamic_text:
            return {"parent_kwd": identity.replace("-", ".").split("."),
                    "parent_kwd.keyword": [identity]}
        return {"parent_kwd": [identity]}

    assert matches(query, indexed(parent))
    assert not matches(query, indexed(parent + ".other"))
    assert not matches(query, indexed("another-topic"))


def test_parent_filter_is_used_by_search_update_and_delete():
    tree = ast.parse((ROOT / "rag/utils/es_conn.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ESConnection")
    for method in ("search", "update", "delete"):
        node = next(n for n in cls.body if getattr(n, "name", None) == method)
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "_navigation_parent_filter" for n in ast.walk(node)), method
