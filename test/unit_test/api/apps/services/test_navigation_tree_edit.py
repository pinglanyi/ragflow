import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
spec = importlib.util.spec_from_file_location("navigation_tree_edit_under_test", ROOT / "api/apps/services/navigation_tree_edit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def corpus():
    def topic(name, parent, docs, depth):
        return {"name": name, "id": name, "type_kwd": "nav_cluster", "parent_kwd": parent,
                "depth_int": depth, "doc_ids_kwd": docs, "doc_count_int": len(docs), "content_with_weight": "{}"}
    return [topic("a", "root", ["d"], 0), topic("b", "root", [], 0), topic("sub", "a", ["d"], 1),
            {"id": "doc-row", "name": "d", "doc_id": "d", "type_kwd": "nav_doc", "parent_kwd": "sub",
             "depth_int": 2, "content_with_weight": '{"graph_content":"source evidence"}'}]


def apply(rows, changes, name="sub"):
    patches = module.edit_navigation_rows(rows, name, changes)
    updated = {row["name"]: copy.deepcopy(row) for row in rows}
    for original, patch in patches:
        updated[original["name"]].update(patch)
    return updated


def test_move_topic_updates_both_ancestor_memberships_and_preserves_identity():
    rows = corpus()
    original = copy.deepcopy(rows)
    result = apply(rows, {"parent_name": "b", "display_name": "新主题"})
    assert result["a"]["doc_ids_kwd"] == []
    assert result["b"]["doc_ids_kwd"] == ["d"]
    assert result["sub"]["parent_kwd"] == "b"
    assert result["sub"]["id"] == "sub"
    assert result["d"]["parent_kwd"] == "sub"
    assert rows == original


def test_move_topic_to_root_recomputes_descendant_depths():
    result = apply(corpus(), {"parent_name": "root"})
    assert result["sub"]["depth_int"] == 0
    assert result["d"]["depth_int"] == 1
    assert result["a"]["doc_count_int"] == 0


def test_move_document_and_edit_notes_preserves_evidence():
    result = apply(corpus(), {"parent_name": "b", "display_name": "手册", "description": "说明"}, "d")
    assert result["sub"]["doc_ids_kwd"] == result["a"]["doc_ids_kwd"] == []
    assert result["b"]["doc_count_int"] == 1
    assert result["d"]["depth_int"] == 1
    payload = json.loads(result["d"]["content_with_weight"])
    assert payload == {"graph_content": "source evidence", "display_name": "手册", "description": "说明"}


def test_infinity_keyword_list_types_support_edits_and_moves():
    rows = corpus()
    for row in rows:
        row["type_kwd"] = [row["type_kwd"]]
    result = apply(rows, {"parent_name": "b", "display_name": "新主题"})
    assert result["sub"]["parent_kwd"] == "b"
    assert result["a"]["doc_ids_kwd"] == []
    assert result["b"]["doc_ids_kwd"] == ["d"]
    assert result["d"]["type_kwd"] == ["nav_doc"]


def test_numeric_strings_do_not_cause_whole_tree_writes():
    rows = corpus()
    for row in rows:
        row["depth_int"] = str(row["depth_int"])
        if "doc_count_int" in row:
            row["doc_count_int"] = str(row["doc_count_int"])
        row["type_kwd"] = [row["type_kwd"]]
    patches = module.edit_navigation_rows(rows, "sub", {"description": "new note"})
    assert len(patches) == 1
    assert set(patches[0][1]) == {"content_with_weight"}


def test_legacy_duplicate_summary_names_preserve_distinct_document_identities():
    rows = corpus()
    rows[3]["name"] = "same-summary-hash"
    other = copy.deepcopy(rows[3])
    other.update(id="other-row", doc_id="other", content_with_weight='{"description":"other evidence"}')
    rows.append(other)
    rows[0]["doc_ids_kwd"].append("other")
    rows[2]["doc_ids_kwd"].append("other")
    rows[0]["doc_count_int"] = rows[2]["doc_count_int"] = 2
    patches = module.edit_navigation_rows(rows, "sub", {"description": "updated topic"})
    changes = {old["id"]: patch for old, patch in patches}
    assert changes["doc-row"] == {"name": "d"}
    assert changes["other-row"] == {"name": "other"}
    with pytest.raises(ValueError, match="Ambiguous"):
        module.edit_navigation_rows(rows, "same-summary-hash", {"description": "x"})
    # Canonical doc_id works even before the legacy name is migrated.
    patches = module.edit_navigation_rows(rows, "d", {"description": "only first doc"})
    first = next(patch for old, patch in patches if old["id"] == "doc-row")
    assert json.loads(first["content_with_weight"])["description"] == "only first doc"
    assert next(patch for old, patch in patches if old["id"] == "other-row") == {"name": "other"}


@pytest.mark.parametrize("name,changes", [
    ("a", {"parent_name": "sub"}), ("sub", {"parent_name": "sub"}),
    ("d", {"parent_name": "root"}), ("a", {"parent_name": "d"}),
    ("a", {"parent_name": "missing"}), ("missing", {"description": "x"}),
    ("a", {"display_name": "  "}), ("a", {"description": None}),
    ("a", {"name": "new-id"}), ("a", None),
])
def test_invalid_moves_or_edits_leave_original_unchanged(name, changes):
    rows = corpus()
    original = copy.deepcopy(rows)
    with pytest.raises(ValueError):
        module.edit_navigation_rows(rows, name, changes)
    assert rows == original
