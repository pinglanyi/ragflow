"""Declared titles enrich keyword indexing without changing parsed evidence."""

import ast
import asyncio
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("declared_title_tested", ROOT / "rag/nlp/declared_title.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
TOKENIZER = SimpleNamespace(tokenize=lambda s: s.lower(), fine_grained_tokenize=lambda s: "fine:" + s)


def test_titles_support_first_nonempty_chunk_and_cjk_without_numeric_noise():
    chunks = [{"content_with_weight": ""}, {"content_with_weight": "Title: The ES750 用户手册 2026 Wikipedia\nName: ES750 控制器\nFullname: EIT CAN"}]
    assert MODULE.declared_title_terms(chunks) == ["es750", "用户手册", "控制器", "eit", "can"]


def test_only_first_nonempty_chunks_header_is_used():
    assert MODULE.declared_title_terms([{"content_with_weight": "ordinary body"}, {"content_with_weight": "Title: hidden"}]) == []
    assert MODULE.declared_title_terms([{"content_with_weight": "x\n" * 20 + "Title: hidden"}]) == []


def test_title_terms_are_bounded_and_deduplicated():
    assert len(MODULE.declared_title_terms([{"content_with_weight": "title: " + " ".join(f"model{i}" for i in range(50))}])) == 20
    assert len(" ".join(MODULE.declared_title_terms([{"content_with_weight": "title: " + "测" * 10000}]))) <= 512


def test_enrichment_preserves_filename_content_vectors_and_existing_titles():
    chunks = [{"content_with_weight": "Title: ES750 Controller", "docnm_kwd": "17504.pdf", "title_tks": "17504", "title_sm_tks": "17504", "q_3_vec": [1, 2, 3]},
              {"content_with_weight": "CAN wiring", "title_tks": "other"}]
    before = copy.deepcopy(chunks)
    assert MODULE.enrich_declared_titles(chunks, TOKENIZER) is chunks
    assert chunks[0]["title_tks"] == "17504 es750 controller"
    assert chunks[1]["title_tks"] == "other es750 controller"
    for key in ("content_with_weight", "docnm_kwd", "q_3_vec"):
        assert chunks[0][key] == before[0][key]
    MODULE.enrich_declared_titles(chunks, TOKENIZER)
    assert chunks[0]["title_tks"] == "17504 es750 controller"


def test_no_header_is_exact_noop_and_compiled_products_are_untouched():
    chunks = [{"content_with_weight": "ordinary text", "title_tks": "old", "title_sm_tks": "old-fine"}]
    before = copy.deepcopy(chunks)
    MODULE.enrich_declared_titles(chunks, TOKENIZER)
    assert chunks == before
    chunks = [{"content_with_weight": "Title: CAN controller", "compile_kwd": "wiki", "title_tks": "old"}]
    MODULE.enrich_declared_titles(chunks, TOKENIZER)
    assert chunks[0]["title_tks"] == "old"


@pytest.mark.parametrize("from_page,expected", [(0, "17504 es750 controller"), (5, "17504")])
def test_actual_chunk_service_enriches_after_parsing_before_upload(from_page, expected):
    source = ast.parse((ROOT / "rag/svr/task_executor_refactor/chunk_service.py").read_text(encoding="utf-8"))
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "ChunkService")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "build_chunks")
    fn.decorator_list = []
    chunks = [{"content_with_weight": "title: ES750 controller", "title_tks": "17504"}]

    async def parsed(*args):
        return chunks

    async def upload(cks):
        assert cks[0]["title_tks"] == expected
        return cks

    async def noop(*args):
        pass

    ctx = SimpleNamespace(size=1, parser_id="naive", parser_config={}, kb_parser_config={}, from_page=from_page, to_page=10,
                          language="English", recording_context=SimpleNamespace(record=lambda *args: None))
    ns = {"List": list, "Dict": dict, "Any": object, "settings": SimpleNamespace(DOC_MAXIMUM_SIZE=100),
          "get_parser": lambda name: object(), "normalize_overlapped_percent": lambda value: value,
          "DEFAULT_DELIMITER": "\n", "run_chunking": parsed, "extract_outline": noop, "TAG_FLD": "tag",
          "enrich_declared_titles": MODULE.enrich_declared_titles, "rag_tokenizer": TOKENIZER}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "actual-chunk-service", "exec"), ns)  # noqa: S102 - trusted repository method
    self = SimpleNamespace(_task_context=ctx, _prepare_docs_and_upload=upload)
    assert asyncio.run(ns["build_chunks"](self, b"test")) is chunks
