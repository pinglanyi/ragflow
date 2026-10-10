"""Navigation modes preserve the canonical tree and document authorization."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[5]


def load_function(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(item for item in tree.body if getattr(item, "name", None) == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def node(name, docs, children=()):
    return SimpleNamespace(folder_name=name, label=name, summary=name, vec=[1.0], doc_ids=docs, children=list(children))


def test_projection_keeps_intermediate_topics_and_unique_paths():
    project = load_function(
        "rag/svr/task_executor_refactor/dataset_skill_generator.py",
        "nav_clusters_from_skill_roots", {},
    )
    leaf_a, leaf_b = node("a", ["a"]), node("b", ["b"])
    root = node("root-topic", ["a", "b"], [
        node("same-label", ["a"], [leaf_a]),
        node("same-label", ["b"], [leaf_b]),
    ])
    result = project([root], {"a": "A.pdf", "b": "B.pdf"})
    assert result[0]["documents"] == []
    branches = result[0]["children"]
    assert len(branches) == 2
    assert branches[0]["name"] != branches[1]["name"]
    assert branches[0]["display_name"] == branches[1]["display_name"]
    assert branches[0]["documents"][0]["name"] == "A.pdf"
    assert result[0]["doc_ids"] == ["a", "b"]


def test_flat_corpus_still_produces_a_topic_with_document_leaves():
    project = load_function(
        "rag/svr/task_executor_refactor/dataset_skill_generator.py",
        "nav_clusters_from_skill_roots", {},
    )
    result = project([node("topic", ["a"], [node("a", ["a"])])], {"a": "A.pdf"})
    assert result[0]["children"] == []
    assert result[0]["documents"][0]["doc_id"] == "a"


def test_two_layer_read_uses_membership_without_changing_hierarchy(monkeypatch):
    import sys
    from types import ModuleType

    calls = []
    cluster = {"doc_ids_kwd": ["a", "b", "a"]}
    nav = ModuleType("rag.advanced_rag.knowlege_compile.dataset_nav")
    nav.nav_cluster_id = lambda kb, name: f"{kb}:{name}"
    monkeypatch.setitem(sys.modules, nav.__name__, nav)

    async def run_sync(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def documents(**kwargs):
        calls.append(kwargs)
        return ([{"id": "a", "name": "A.pdf", "meta_fields": {"description": "summary"}}], 1)

    async def page_search(_dataset, _tenant, condition, _page, _size):
        assert condition["type_kwd"] == ["nav_doc"]
        assert condition["doc_id"] == ["a", "b"]
        assert "parent_kwd" not in condition
        return True, {"total": 1, "items": [{"doc_id": "a", "display_name": "人工标签"}]}

    namespace = {
        "KnowledgebaseService": SimpleNamespace(accessible=lambda *_args: True, get_by_id=lambda _id: (True, SimpleNamespace(tenant_id="owner"))),
        "DocumentService": SimpleNamespace(get_by_kb_id=documents),
        "settings": SimpleNamespace(docStoreConn=SimpleNamespace(get=lambda *_args: cluster)),
        "thread_pool_exec": run_sync,
        "_compiled_index_or_none": lambda *_args: ("index", None),
        "_NAV_COMPILE_KWD": "dataset_nav", "_nav_search": page_search,
    }
    read = load_function("api/apps/services/dataset_api_service.py", "list_nav_children", namespace)
    ok, result = asyncio.run(read("kb", "user", "topic", tree_mode="two_layer"))
    assert ok
    assert [item["doc_id"] for item in result["items"]] == ["a"]
    assert result["items"][0]["display_name"] == "人工标签"
    assert calls[0]["kb_id"] == "kb"
    assert calls[0]["doc_ids"] == ["a", "b"]
    assert cluster == {"doc_ids_kwd": ["a", "b", "a"]}


def test_two_layer_read_checks_access_before_reading_membership():
    namespace = {"KnowledgebaseService": SimpleNamespace(accessible=lambda *_args: False)}
    read = load_function("api/apps/services/dataset_api_service.py", "list_nav_children", namespace)
    assert asyncio.run(read("kb", "user", "topic", tree_mode="two_layer")) == (False, "No authorization.")
    assert asyncio.run(read("kb", "user", "topic", tree_mode="invalid"))[0] is False


def test_hierarchical_read_keeps_direct_children():
    async def nav_search(_dataset, _user, condition, _page, _page_size):
        assert condition["parent_kwd"] == ["topic"]
        return True, {"total": 1, "items": [{"name": "subtopic", "type": "cluster"}]}
    namespace = {"KnowledgebaseService": SimpleNamespace(accessible=lambda *_args: True),
                 "_NAV_COMPILE_KWD": "dataset_nav", "_nav_search": nav_search}
    read = load_function("api/apps/services/dataset_api_service.py", "list_nav_children", namespace)
    assert asyncio.run(read("kb", "user", "topic"))[1]["items"][0]["type"] == "cluster"


def test_edit_denies_unauthorized_users_before_locking():
    namespace = {"KnowledgebaseService": SimpleNamespace(accessible=lambda *_args: False)}
    edit = load_function("api/apps/services/dataset_api_service.py", "update_nav_node", namespace)
    assert asyncio.run(edit("kb", "user", "topic", {"description": "new"})) == (False, "No authorization.")


def test_incremental_document_changes_update_all_ancestors_and_keep_empty_topics():
    rows = {"a": {"parent_kwd": "root", "doc_ids_kwd": ["d"], "doc_count_int": 1},
            "b": {"parent_kwd": "a", "doc_ids_kwd": ["d"], "doc_count_int": 1}}
    async def get(_tenant, _kb, key):
        return rows.get(key)
    async def save(_tenant, _kb, _row):
        pass
    namespace = {"_store_get": get, "_store_upsert": save, "nav_cluster_id": lambda _kb, name: name}
    update = load_function("rag/advanced_rag/knowlege_compile/dataset_nav.py", "_update_nav_ancestor_membership", namespace)
    asyncio.run(update("owner", "kb", "b", "new", add=True))
    assert rows["a"]["doc_ids_kwd"] == rows["b"]["doc_ids_kwd"] == ["d", "new"]
    asyncio.run(update("owner", "kb", "b", "d", add=False))
    asyncio.run(update("owner", "kb", "b", "new", add=False))
    assert rows["a"]["doc_ids_kwd"] == rows["b"]["doc_ids_kwd"] == []
    assert rows["a"]["doc_count_int"] == rows["b"]["doc_count_int"] == 0


@pytest.mark.parametrize("fail_write", [False, True])
@pytest.mark.parametrize("mutating_backend", [False, True])
def test_edit_uses_exact_id_updates_for_zero_depth_and_empty_membership(monkeypatch, fail_write, mutating_backend):
    import sys
    import json
    import logging
    from types import ModuleType
    import copy
    edit_navigation_rows = load_function("api/apps/services/navigation_tree_edit.py", "edit_navigation_rows", {"copy": copy, "json": json})

    modules = {}
    for modname in ("common.doc_store.doc_store_base", "api.apps.services.navigation_tree_edit",
                    "rag.advanced_rag.knowlege_compile.dataset_nav"):
        modules[modname] = ModuleType(modname)
        monkeypatch.setitem(sys.modules, modname, modules[modname])
    modules["common.doc_store.doc_store_base"].OrderByExpr = lambda: None
    modules["api.apps.services.navigation_tree_edit"].edit_navigation_rows = edit_navigation_rows
    modules["rag.advanced_rag.knowlege_compile.dataset_nav"]._tokenize = lambda text: text
    modules["rag.advanced_rag.knowlege_compile.dataset_nav"]._fine_tokenize = lambda text: text
    rows = {
        "root-id": {"name": "topic", "type_kwd": "nav_cluster", "parent_kwd": "root", "depth_int": 0,
                    "doc_ids_kwd": ["d"], "doc_count_int": 1, "content_with_weight": "{}"},
        "sub-id": {"name": "sub", "type_kwd": "nav_cluster", "parent_kwd": "topic", "depth_int": 1,
                   "doc_ids_kwd": ["d"], "doc_count_int": 1, "content_with_weight": "{}"},
        "doc-id": {"name": "d", "doc_id": "d", "type_kwd": "nav_doc", "parent_kwd": "sub", "depth_int": 2,
                   "content_with_weight": "{}"},
    }
    calls, releases, refreshes = [], [], []
    async def run_sync(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    async def acquire(_kb):
        return "lock"
    def update(condition, patch, *_args):
        assert isinstance(condition["id"], str)  # ES bulk-update ignores zero/empty values.
        calls.append((condition, copy.deepcopy(patch)))
        if mutating_backend and "content_with_weight" in patch:
            patch["content"] = patch.pop("content_with_weight")
            patch.pop("content_ltks", None)
            patch.pop("content_sm_ltks", None)
        if fail_write and len(calls) == 2:
            return False
        return True
    namespace = {"KnowledgebaseService": SimpleNamespace(accessible=lambda *_args: True,
        get_by_id=lambda _id: (True, SimpleNamespace(tenant_id="owner"))),
        "_acquire_nav_lock": acquire, "_release_nav_lock": lambda *args: releases.append(args),
        "_compiled_index_or_none": lambda *_args: ("index", None), "thread_pool_exec": run_sync,
        "_NAV_FIELDS": [], "_NAV_COMPILE_KWD": "dataset_nav", "json": json, "logging": logging,
        "settings": SimpleNamespace(docStoreConn=SimpleNamespace(search=lambda *_args: {},
            get_fields=lambda *_args: rows, get_total=lambda *_args: len(rows), update=update,
            refresh_idx=lambda index: refreshes.append(index))),
    }
    edit = load_function("api/apps/services/dataset_api_service.py", "update_nav_node", namespace)
    ok, result = asyncio.run(edit("kb", "user", "sub", {"parent_name": "root", "display_name": "renamed"}))
    if fail_write:
        assert not ok
        assert len(calls) == 4  # Two attempted writes, then restore in reverse.
        assert calls[-1][1]["doc_ids_kwd"] == ["d"]
        assert calls[-1][1]["doc_count_int"] == 1
        assert calls[-2][1]["content_with_weight"] == "{}"
        assert "content" not in calls[-2][1]
        assert releases == [("lock", "kb")]
        return
    assert ok, result
    patches = {condition["id"]: patch for condition, patch in calls}
    assert patches["sub-id"]["depth_int"] == 0
    assert patches["root-id"]["doc_ids_kwd"] == []
    assert patches["root-id"]["doc_count_int"] == 0
    assert releases == [("lock", "kb")]
    assert refreshes == ["index"]
