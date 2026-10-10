# These tests execute trusted local ASTs to isolate parser logic from OCR/model services.
# ruff: noqa: S102
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[5]


def test_docling_flow_forwards_saved_conversion_options():
    scope = load_pdf_method()
    scope["os"] = SimpleNamespace(environ={})
    backend = Mock()
    backend.parse_pdf.return_value = ([], [])
    scope["DoclingParser"] = Mock(return_value=backend)
    process = SimpleNamespace(
        _param=SimpleNamespace(setups={"pdf": {"parse_method": "docling", "output_format": "json",
                                             "docling_do_ocr": False, "docling_pdf_backend": "dlparse_v4"}}),
        _canvas=SimpleNamespace(_tenant_id="tenant"), callback=Mock(), set_output=Mock(),
    )
    scope["_pdf"](process, "a.pdf", b"pdf")
    assert backend.parse_pdf.call_args.kwargs["do_ocr"] is False
    assert backend.parse_pdf.call_args.kwargs["pdf_backend"] == "dlparse_v4"


def test_docling_dataset_forwards_saved_conversion_options():
    tree = ast.parse((ROOT / "rag/app/naive.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "by_docling")
    backend = Mock()
    backend.check_installation.return_value = True
    backend.parse_pdf.return_value = ([], [])
    scope = {"MAXIMUM_PAGE_NUMBER": 1000, "DoclingParser": Mock(return_value=backend), "os": SimpleNamespace(environ={})}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<naive>", "exec"), scope)
    scope["by_docling"]("a.pdf", binary=b"pdf", parser_config={"docling_do_ocr": False, "docling_pdf_backend": "dlparse_v4"})
    assert backend.parse_pdf.call_args.kwargs["do_ocr"] is False
    assert backend.parse_pdf.call_args.kwargs["pdf_backend"] == "dlparse_v4"


def _load_flow_utils(monkeypatch):
    tree = ast.parse((ROOT / "rag/flow/parser/utils.py").read_text(encoding="utf-8"))
    method = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "enhance_media_sections_with_vision")
    scope = {
        "LLMBundle": Mock(),
        "VisionFigureParser": Mock(return_value=Mock(return_value=[])),
        "resolve_model_config": Mock(),
        "get_tenant_default_model_by_type": Mock(),
        "LLMType": SimpleNamespace(VISION="vision"),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<utils>", "exec"), scope)
    return SimpleNamespace(**scope)


def load_pdf_method():
    tree = ast.parse((ROOT / "rag/flow/parser/parser.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Parser")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_pdf")
    scope = {
        "MAXIMUM_PAGE_NUMBER": 1000000,
        "random": SimpleNamespace(randint=lambda *_: 1),
        "TenantModelService": SimpleNamespace(get_by_id=lambda _: (False, None)),
        "PlainParser": Mock(),
        "VisionParser": Mock(),
        "LLMBundle": Mock(),
        "resolve_model_config": Mock(),
        "get_tenant_default_model_by_type": Mock(),
        "LLMType": SimpleNamespace(VISION="vision"),
        "RAGFlowPdfParser": SimpleNamespace(extract_positions=lambda _: []),
        "normalize_pdf_items_metadata": lambda _: None,
        "enhance_media_sections_with_vision": Mock(),
    }
    helper_path = ROOT / "rag/flow/parser/pdf_page_ranges.py"
    exec(compile(helper_path.read_text(encoding="utf-8"), str(helper_path), "exec"), scope)
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<parser>", "exec"), scope)
    return scope


@pytest.mark.parametrize("method", ["plain_text", "Plain Text", "selected-vision"])
def test_pdf_flow_honors_disjoint_ranges_without_duplicate_pages(method):
    scope = load_pdf_method()
    backend = Mock(outlines=[])
    backend.return_value = ([], [])
    scope["PlainParser"].return_value = backend
    scope["VisionParser"].return_value = backend
    process = SimpleNamespace(
        _param=SimpleNamespace(setups={"pdf": {"parse_method": method, "output_format": "json", "pages": [[4, 5], [2, 3], [3, 3], [8, 8]], "lang": "English"}}),
        _canvas=SimpleNamespace(_tenant_id="tenant"),
        callback=Mock(),
        set_output=Mock(),
    )
    scope["_pdf"](process, "a.pdf", b"pdf")
    assert [(call.kwargs.get("from_page"), call.kwargs.get("to_page")) for call in backend.call_args_list] == [(1, 5), (7, 8)]
    if method in ("plain_text", "Plain Text"):
        scope["PlainParser"].assert_called_once()
        scope["VisionParser"].assert_not_called()


def test_global_vision_disabled_does_not_resolve_model(monkeypatch):
    utils = _load_flow_utils(monkeypatch)
    sections = [{"text": "OCR", "image": object(), "doc_type_kwd": "image"}]
    assert utils.enhance_media_sections_with_vision(sections, "tenant", enabled=False) is sections
    utils.LLMBundle.assert_not_called()


def test_global_vision_uses_selected_model_instead_of_family_model(monkeypatch):
    utils = _load_flow_utils(monkeypatch)
    sections = [{"text": "OCR", "image": object(), "doc_type_kwd": "image"}]
    utils.enhance_media_sections_with_vision(sections, "tenant", {"llm_id": "family"}, enabled=True, global_vlm={"llm_id": "global"})
    utils.resolve_model_config.assert_called_once_with("tenant", "vision", "global")


def test_global_vision_empty_selection_uses_tenant_default(monkeypatch):
    utils = _load_flow_utils(monkeypatch)
    utils.enhance_media_sections_with_vision([{"image": object(), "doc_type_kwd": "image"}], "tenant", {"llm_id": "family"}, enabled=True, global_vlm={})
    utils.resolve_model_config.assert_not_called()
    utils.get_tenant_default_model_by_type.assert_called_once_with("tenant", "vision")


def test_deepdoc_small_window_returns_source_page_numbers():
    tree = ast.parse((ROOT / "deepdoc/parser/pdf_parser.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RAGFlowPdfParser")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "parse_into_bboxes")
    scope = {"MAXIMUM_PAGE_NUMBER": 1000000, "os": SimpleNamespace(getenv=lambda *_: "50"), "extract_pdf_outlines": lambda _: [], "logging": Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<pdf>", "exec"), scope)
    process = SimpleNamespace(
        total_page_number=Mock(return_value=10),
        __images__=Mock(),
        _parse_loaded_window_into_bboxes=Mock(return_value=[{"page_number": 1}]),
        _to_global_boxes=lambda boxes: [{**b, "page_number": b["page_number"] + 2} for b in boxes],
    )
    assert scope["parse_into_bboxes"](process, b"pdf", from_page=2, to_page=4) == [{"page_number": 3}]


@pytest.mark.parametrize("pages", ["2,3", [[0, 3]], [[3, 2]], [[1.5, 3]], [[True, 2]], [[1]], [[1, 2], ["3", 4]]])
def test_page_ranges_reject_invalid_values(pages):
    scope = load_pdf_method()
    with pytest.raises(ValueError):
        scope["pdf_page_ranges"](pages)


def test_ranges_intersect_worker_bounds_without_widening_empty_selection():
    normalize = load_pdf_method()["pdf_page_ranges"]
    assert normalize([[1, 3], [8, 10]], 2, 9) == [(2, 3), (7, 9)]
    assert normalize([[1, 3]], 5, 9) == []


def test_flow_deepdoc_honors_ranges():
    scope = load_pdf_method()
    backend = Mock(outlines=[])
    backend.parse_into_bboxes.return_value = []
    scope["RAGFlowPdfParser"] = Mock(return_value=backend)
    process = SimpleNamespace(
        _param=SimpleNamespace(setups={"pdf": {"parse_method": "deepdoc", "output_format": "json", "pages": [[3, 4], [8, 9]]}}),
        _canvas=SimpleNamespace(_tenant_id="tenant"),
        callback=Mock(),
        set_output=Mock(),
    )
    scope["_pdf"](process, "a.pdf", b"pdf")
    assert [(c.kwargs["from_page"], c.kwargs["to_page"]) for c in backend.parse_into_bboxes.call_args_list] == [(2, 4), (7, 9)]


def test_global_flags_reach_all_existing_media_enhancement_calls():
    tree = ast.parse((ROOT / "rag/flow/parser/parser.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "enhance_media_sections_with_vision"]
    assert len(calls) == 4
    assert all({"enabled", "global_vlm", "lang"} <= {k.arg for k in call.keywords} for call in calls)


def test_missing_global_flag_retains_family_model(monkeypatch):
    utils = _load_flow_utils(monkeypatch)
    utils.enhance_media_sections_with_vision([{"image": object(), "doc_type_kwd": "image"}], "tenant", {"llm_id": "family"})
    utils.resolve_model_config.assert_called_once_with("tenant", "vision", "family")


def test_empty_pdf_selection_returns_without_resolving_or_parsing():
    scope = load_pdf_method()
    outputs = {}
    process = SimpleNamespace(
        _param=SimpleNamespace(setups={"pdf": {"parse_method": "selected-vision", "output_format": "json", "pages": [[1, 2]]}}),
        _canvas=SimpleNamespace(_tenant_id="tenant"),
        callback=Mock(),
        set_output=lambda k, v: outputs.__setitem__(k, v),
    )
    scope["_pdf"](process, "a.pdf", b"pdf", from_page=5, to_page=8)
    assert outputs["json"] == []
    scope["resolve_model_config"].assert_not_called()
    scope["VisionParser"].assert_not_called()


def test_plain_pdf_parser_already_limits_text_to_requested_pages():
    tree = ast.parse((ROOT / "deepdoc/parser/pdf_parser.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PlainParser")
    pages = [SimpleNamespace(extract_text=lambda n=n: f"page {n}") for n in range(1, 6)]
    scope = {"MAXIMUM_PAGE_NUMBER": 100000, "pdf2_read": lambda _: SimpleNamespace(pages=pages), "extract_pdf_outlines": lambda _: [], "logging": Mock()}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "<plain>", "exec"), scope)
    assert scope["PlainParser"]()("sample.pdf", from_page=2, to_page=4)[0] == [("page 3", ""), ("page 4", "")]


def test_vision_pdf_parser_already_renders_range_with_source_page_tags(monkeypatch):
    import sys
    from contextlib import nullcontext
    from types import ModuleType

    tree = ast.parse((ROOT / "deepdoc/parser/pdf_parser.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VisionParser")
    images = [SimpleNamespace(size=(300, 600), name=f"page {n}") for n in range(1, 6)]
    pages = [SimpleNamespace(to_image=lambda resolution, img=img: SimpleNamespace(annotated=img)) for img in images]
    lock_key = "test_vision_pdf_lock"
    monkeypatch.setitem(sys.modules, lock_key, nullcontext())
    picture = ModuleType("rag.app.picture")
    picture.vision_llm_chunk = lambda binary, **_: binary.name
    monkeypatch.setitem(sys.modules, "rag.app.picture", picture)
    scope = {
        "MAXIMUM_PAGE_NUMBER": 100000,
        "RAGFlowPdfParser": object,
        "pdfplumber": SimpleNamespace(open=lambda _: SimpleNamespace(pages=pages)),
        "sys": sys,
        "LOCK_KEY_pdfplumber": lock_key,
        "logging": Mock(),
        "vision_llm_describe_prompt": lambda page: str(page),
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "<vision>", "exec"), scope)
    parser = scope["VisionParser"](object())
    result, _ = parser("sample.pdf", from_page=2, to_page=4)
    assert [text for text, _ in result] == ["page 3", "page 4"]
    assert [tag.split("\t")[0] for _, tag in result] == ["@@3", "@@4"]


def test_invalid_explicit_global_model_does_not_switch_to_another_model(monkeypatch):
    utils = _load_flow_utils(monkeypatch)
    utils.resolve_model_config.side_effect = ValueError("unknown model")
    sections = [{"image": object(), "doc_type_kwd": "image", "text": "original"}]
    assert utils.enhance_media_sections_with_vision(sections, "tenant", enabled=True, global_vlm={"llm_id": "missing"}) is sections
    utils.get_tenant_default_model_by_type.assert_not_called()
    utils.LLMBundle.assert_not_called()
