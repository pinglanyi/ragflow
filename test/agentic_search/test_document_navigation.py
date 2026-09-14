"""Behavioral tests without starting the API server or loading model weights."""

import asyncio
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "rag/advanced_rag/harness/tools/inspector.py"


def load_inspector():
    spec = importlib.util.spec_from_file_location("navigation_inspector_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def chunk(id, doc="doc", text=None):
    return {"id": id, "chunk_id": id, "doc_id": doc, "kb_id": "kb", "docnm_kwd": "manual.pdf", "content_with_weight": text or id, "positions": [[1, 0, 20, 0, 20]], "image_id": "page-image"}


class Tools:
    def __init__(self):
        self.rows = [chunk("before"), chunk("anchor"), chunk("unseen", text="温度超过40度，需人工确认。"), chunk("last")]
        self.kbinfos = {"chunks": [self.rows[1], chunk("unrelated", "other")], "doc_aggs": []}
        self.calls = []

    async def iter_document_chunks(self, doc_id):
        self.calls.append(doc_id)
        for row in self.rows:
            if row["doc_id"] == doc_id:
                yield dict(row)


class InspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_inspector()

    def setUp(self):
        self.tools = Tools()

    def test_adjacent_reads_unseen_same_document_chunk(self):
        result = asyncio.run(self.module.request_adjacent(self.tools, "anchor", count=1))
        self.assertEqual([c["id"] for c in result["chunks"]], ["unseen"])
        self.assertEqual(result["chunks"][0]["image_id"], "page-image")
        self.assertEqual(self.tools.calls, ["doc"])

    def test_open_expands_both_directions_in_document_order(self):
        result = asyncio.run(self.module.open_context(self.tools, "anchor", width=500))
        self.assertEqual([c["id"] for c in result["chunks"]], ["before", "anchor", "unseen", "last"])
        self.assertEqual(len(self.tools.kbinfos["chunks"]), 2)

    def test_previous_keeps_reading_order(self):
        self.tools.kbinfos["chunks"].append(self.tools.rows[3])
        result = asyncio.run(self.module.request_adjacent(self.tools, "last", direction="prev", count=2))
        self.assertEqual([c["id"] for c in result["chunks"]], ["anchor", "unseen"])

    def test_unknown_anchor_fails_without_scanning(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.module.request_adjacent(self.tools, "invented"))
        self.assertFalse(self.tools.calls)

    def test_invalid_direction_is_not_silently_next(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.module.request_adjacent(self.tools, "anchor", direction="wrong"))

    def test_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.module.request_adjacent(self.tools, "anchor", count=-1))

    def test_grep_searches_unseen_text(self):
        result = asyncio.run(self.module.grep_within(self.tools, "doc", "40度"))
        self.assertEqual([c["id"] for c in result["chunks"]], ["unseen"])
        self.assertEqual(result["chunks"][0]["content_with_weight"], self.tools.rows[2]["content_with_weight"])

    def test_read_range_uses_document_order(self):
        fn = getattr(self.module, "read_document", None)
        self.assertTrue(callable(fn), "read_document must be implemented")
        result = asyncio.run(fn(self.tools, "doc", start=2, count=1))
        self.assertEqual([c["id"] for c in result["chunks"]], ["unseen"])


if __name__ == "__main__":
    unittest.main()
