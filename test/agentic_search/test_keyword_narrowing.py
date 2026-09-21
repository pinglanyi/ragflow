"""Model-generated keyword lists must not erase retrieved evidence."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


def _load_search():
    common = ModuleType("common")
    common.settings = SimpleNamespace()
    path = Path(__file__).resolve().parents[2] / "rag/advanced_rag/harness/tools/search.py"
    spec = importlib.util.spec_from_file_location("keyword_search_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"common": common}):
        spec.loader.exec_module(module)
    return module


def test_space_separated_keywords_keep_identifier_evidence():
    search = _load_search()
    chunks = [
        {"chunk_id": "e502", "content_with_weight": "E502 has ten thermocouple inputs."},
        {"chunk_id": "unrelated", "content_with_weight": "Another product has eight channels."},
    ]

    result = search._narrow_by_keywords(chunks, "E502 10-CH temperature collection module function")

    assert [item["chunk_id"] for item in result] == ["e502"]


def test_chinese_terms_keep_can2_evidence_without_exact_phrase():
    search = _load_search()
    chunks = [
        {"chunk_id": "can2", "content_with_weight": "CAN2 总线连接扩展模块；接线后确认接地。"},
        {"chunk_id": "unrelated", "content_with_weight": "普通电源开关的说明。"},
    ]

    result = search._narrow_by_keywords(chunks, "CAN2扩展模块 接线 接地 规范")

    assert [item["chunk_id"] for item in result] == ["can2"]


def test_single_keyword_and_comma_terms_remain_searchable():
    search = _load_search()
    chunks = [{"chunk_id": "e502", "content_with_weight": "E502 温度采集模块。"}]

    assert len(search._narrow_by_keywords(chunks, "E502")) == 1
    assert len(search._narrow_by_keywords(chunks, "E502,temperature")) == 1
    assert search._narrow_by_keywords(chunks, "CAN2 接地") == []


def test_matching_phrase_keeps_precision_before_term_fallback():
    search = _load_search()
    chunks = [
        {"chunk_id": "label", "content_with_weight": "E502 10-CH TEMP COLLECTION"},
        {"chunk_id": "identifier-only", "content_with_weight": "E502 is shown elsewhere."},
    ]

    result = search._narrow_by_keywords(chunks, "E502 10-CH TEMP COLLECTION")

    assert [item["chunk_id"] for item in result] == ["label"]
