import io
import unittest
from unittest.mock import patch

from PIL import Image

from rag.svr.multimodal_source_renderer import (
    OfficeRenderError,
    RenderedVisual,
    convert_office_to_pdf,
    render_chunk_visuals,
)


class MultimodalSourceRendererTest(unittest.TestCase):
    def test_attached_chunk_image_keeps_original_position_locator(self):
        chunk = {
            "image": Image.new("RGB", (32, 24), "white"),
            "page_num_int": [3],
            "position_int": [[3, 10, 30, 20, 40]],
            "doc_id": "doc-1",
        }

        visuals = render_chunk_visuals("manual.pdf", b"pdf", chunk, 0)

        self.assertEqual(len(visuals), 1)
        self.assertTrue(visuals[0].png.startswith(b"\x89PNG"))
        self.assertEqual(visuals[0].locator["source_type"], "pdf")
        self.assertEqual(visuals[0].locator["page"], 3)
        self.assertEqual(visuals[0].locator["positions"], chunk["position_int"])
        self.assertEqual(chunk["doc_id"], "doc-1")

    def test_text_chunk_gets_deterministic_canvas_and_line_locator(self):
        chunk = {
            "content_with_weight": "line one\nline two",
            "source_line_start_int": 11,
            "source_line_end_int": 12,
        }

        first = render_chunk_visuals("notes.txt", b"line one\nline two", chunk, 2)
        second = render_chunk_visuals("notes.txt", b"line one\nline two", chunk, 2)

        self.assertEqual(first[0].png, second[0].png)
        self.assertEqual(first[0].locator["source_type"], "text")
        self.assertEqual(first[0].locator["line_start"], 11)
        self.assertEqual(first[0].locator["line_end"], 12)

    def test_presentation_uses_slide_numbers_to_render_converted_pdf_pages(self):
        converted = b"converted-pdf"
        rendered = RenderedVisual(b"png", {"source_type": "pdf", "page": 2}, "Page 2")
        chunk = {"page_num_int": [2], "position_int": [[2, 0, 0, 0, 0]], "content_with_weight": "slide"}

        with patch("rag.svr.multimodal_source_renderer.convert_office_to_pdf", return_value=converted) as convert, patch(
            "rag.svr.multimodal_source_renderer._render_pdf_pages", return_value=[rendered]
        ) as render:
            result = render_chunk_visuals("deck.pptx", b"pptx", chunk, 0)

        convert.assert_called_once_with("deck.pptx", b"pptx")
        render.assert_called_once_with(converted, [2])
        self.assertEqual(result[0].locator["source_type"], "presentation")
        self.assertEqual(result[0].locator["slide"], 2)
        self.assertEqual(result[0].locator["rendered_page"], 2)

    def test_presentation_conversion_and_rendered_pages_are_cached_per_document(self):
        cache = {}
        rendered = RenderedVisual(b"png", {"source_type": "pdf", "page": 2}, "Page 2")
        chunk = {"page_num_int": [2], "content_with_weight": "slide"}

        with patch("rag.svr.multimodal_source_renderer.convert_office_to_pdf", return_value=b"pdf") as convert, patch(
            "rag.svr.multimodal_source_renderer._render_pdf_pages", return_value=[rendered]
        ) as render:
            render_chunk_visuals("deck.pptx", b"pptx", chunk, 0, render_cache=cache)
            render_chunk_visuals("deck.pptx", b"pptx", chunk, 1, render_cache=cache)

        convert.assert_called_once()
        render.assert_called_once()

    def test_office_converter_reports_missing_libreoffice(self):
        with patch("rag.svr.multimodal_source_renderer.shutil.which", return_value=None):
            with self.assertRaisesRegex(OfficeRenderError, "LibreOffice"):
                convert_office_to_pdf("deck.pptx", b"pptx")

    def test_source_image_uses_original_file(self):
        source = io.BytesIO()
        Image.new("RGB", (20, 10), "blue").save(source, format="PNG")

        visuals = render_chunk_visuals("diagram.png", source.getvalue(), {"content_with_weight": "old"}, 0)

        self.assertEqual(visuals[0].locator["source_type"], "image")
        self.assertEqual(visuals[0].locator["pixel_bounds"], [0, 0, 20, 10])


if __name__ == "__main__":
    unittest.main()
