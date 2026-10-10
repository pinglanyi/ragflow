"""Exercise the real DeepDOC crop methods without loading OCR models."""

import ast
import logging
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def parser():
    path = Path(__file__).resolve().parents[4] / "deepdoc/parser/pdf_parser.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RAGFlowPdfParser")
    cls.bases = []
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {"extract_positions", "crop"}]
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    scope = {"Image": Image, "np": np, "re": re, "logging": logging}
    exec(compile(module, str(path), "exec"), scope)
    instance = scope[cls.name]()
    instance.page_from = 60
    instance.page_images = [Image.new("RGB", (300, 300), "white"), Image.new("RGB", (600, 180), "red")]
    return instance


def test_valid_crop_preserves_document_page_offset(parser):
    image, positions = parser.crop("text@@1\t10\t50\t20\t40##", need_position=True)
    assert image is not None
    assert positions == [(60, 10, 50, 20, 40)]


def test_reversed_single_page_vertical_coordinates(parser):
    image, positions = parser.crop("text@@1\t10\t50\t80\t20##", need_position=True)
    assert image is not None
    assert positions == [(60, 10, 50, 20, 80)]


def test_wholly_outside_page_does_not_abort_text_chunking(parser):
    assert parser.crop("text@@1\t10\t50\t110\t120##", need_position=True) == (None, None)


def test_partial_overflow_clamps_image_and_reference_coordinates(parser):
    image, positions = parser.crop("text@@1\t90\t120\t80\t120##", need_position=True)
    assert image is not None
    assert positions == [(60, 90, 100, 80, 100)]


def test_cross_page_bottom_is_local_to_last_page(parser):
    image, positions = parser.crop("text@@1-2\t10\t50\t80\t20##", need_position=True)
    assert image is not None
    assert positions == [(60, 10, 50, 80, 100), (61, 10, 50, 0, 20)]


def test_invalid_first_segment_keeps_valid_following_segment(parser):
    image, positions = parser.crop("text@@1\t10\t50\t110\t120## next@@2\t10\t50\t10\t20##", need_position=True)
    assert image is not None
    assert positions == [(61, 10, 50, 10, 20)]
    # A valid body must not become a dimmed context image when context is skipped.
    assert (255, 0, 0) in image.getdata()


def test_zero_area_does_not_create_an_empty_preview(parser):
    assert parser.crop("text@@1\t10\t50\t20\t20##", need_position=True) == (None, None)


def test_reversed_horizontal_coordinates(parser):
    image, positions = parser.crop("text@@1\t50\t10\t20\t40##", need_position=True)
    assert image is not None
    assert positions == [(60, 10, 50, 20, 40)]


def test_three_pages_with_different_heights(parser):
    parser.page_images.append(Image.new("RGB", (300, 240), "blue"))
    image, positions = parser.crop("text@@1-2-3\t10\t50\t80\t20##", need_position=True)
    assert image is not None
    assert positions == [(60, 10, 50, 80, 100), (61, 10, 50, 0, 60), (62, 10, 50, 0, 20)]


@pytest.mark.parametrize("text", ["text without coordinates", "text@@99\t10\t50\t20\t40##"])
def test_missing_or_invalid_page_returns_no_preview(parser, text):
    assert parser.crop(text, need_position=True) == (None, None)
    assert parser.crop(text) is None


def test_body_at_page_start_is_not_dimmed_when_context_is_empty(parser):
    image, positions = parser.crop("text@@2\t10\t50\t0\t20##", need_position=True)
    assert positions == [(61, 10, 50, 0, 20)]
    assert image.getpixel((10, 10)) == (255, 0, 0)
