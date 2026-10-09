"""Web citations identify source content independently of result order."""

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("web_evidence_tested", ROOT / "rag/utils/web_evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def results(text="中文 CAN", url="https://example.org/manual", old_id="random"):
    return {"chunks": [{"chunk_id": old_id, "doc_id": old_id, "content_with_weight": text, "url": url, "similarity": 0.8, "docnm_kwd": "Manual"}],
            "doc_aggs": [{"doc_id": old_id, "url": url, "doc_name": "Manual", "count": 1}]}


def test_repeated_calls_keep_ids_and_citation_fields_aligned():
    first = MODULE.normalize_web_evidence(results())
    again = MODULE.normalize_web_evidence(results(old_id="other-random"))
    assert first == again
    assert first["chunks"][0]["chunk_id"].startswith("web_")
    assert first["chunks"][0]["doc_id"] == first["doc_aggs"][0]["doc_id"]
    assert first["chunks"][0]["similarity"] == 0.8


def test_distinct_content_and_sources_do_not_collide():
    original = MODULE.normalize_web_evidence(results())["chunks"][0]
    changed = MODULE.normalize_web_evidence(results(text="Different"))["chunks"][0]
    other_url = MODULE.normalize_web_evidence(results(url="https://other.org/manual"))["chunks"][0]
    assert len({original["chunk_id"], changed["chunk_id"], other_url["chunk_id"]}) == 3
    assert original["doc_id"] == changed["doc_id"]
    assert original["doc_id"] != other_url["doc_id"]


def test_duplicate_passages_collapse_without_mutating_input():
    source = results()
    source["chunks"] *= 2
    before = copy.deepcopy(source)
    actual = MODULE.normalize_web_evidence(source)
    assert len(actual["chunks"]) == 1
    assert actual["doc_aggs"][0]["count"] == 1
    assert source == before


def test_order_does_not_change_content_identity_and_empty_is_valid():
    a, b = results(), results(text="second", old_id="b")
    merged = {"chunks": a["chunks"] + b["chunks"], "doc_aggs": a["doc_aggs"] + b["doc_aggs"]}
    forward = MODULE.normalize_web_evidence(merged)
    merged["chunks"].reverse()
    reverse = MODULE.normalize_web_evidence(merged)
    assert [c["chunk_id"] for c in forward["chunks"]] == [c["chunk_id"] for c in reverse["chunks"]][::-1]
    assert forward["doc_aggs"][0]["count"] == 2
    assert MODULE.normalize_web_evidence({"chunks": [], "doc_aggs": []}) == {"chunks": [], "doc_aggs": []}
