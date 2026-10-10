"""Exercise the actual decoder without loading GPU/tokenizer dependencies."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def decoder():
    source = Path(__file__).resolve().parents[4] / "rag/nlp/__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "decode_text")
    namespace = {"chardet": SimpleNamespace(detect=lambda _: {"encoding": "gb2312", "confidence": 0.99})}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102 - execute trusted repository definitions in an isolated test scope
    return namespace["decode_text"]


@pytest.mark.parametrize("codec", ["utf-8-sig", "utf-16", "utf-32"])
def test_bom_json_is_decodable(codec):
    text = '{"name": "产品", "body": "a\\ufeffb"}'
    decoded, _ = decoder()(text.encode(codec), document_type="JSON")
    assert json.loads(decoded) == json.loads(text)
    assert not decoded.startswith("\ufeff")


@pytest.mark.parametrize("bom,codec", [(b"\xfe\xff", "utf-16-be"), (b"\xff\xfe", "utf-16-le"),
                                       (b"\x00\x00\xfe\xff", "utf-32-be"), (b"\xff\xfe\x00\x00", "utf-32-le")])
def test_markdown_heading_drops_only_initial_bom(bom, codec):
    text = "# 标题\n\n内部\ufeff保留"
    decoded, _ = decoder()(bom + text.encode(codec), document_type="Markdown")
    assert decoded == text


@pytest.mark.parametrize("codec", ["utf-8", "gb18030"])
def test_unmarked_document_retains_text(codec):
    text = "# 产品手册\nCAN 通信"
    assert decoder()(text.encode(codec))[0] == text
