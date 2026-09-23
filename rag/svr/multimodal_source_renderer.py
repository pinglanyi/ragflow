"""Render parser-independent visual inputs while retaining source locations."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


IMAGE_EXTENSIONS = {".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".odp"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".ods"}
PAGED_OFFICE_EXTENSIONS = PRESENTATION_EXTENSIONS | {
    ".doc",
    ".docx",
    ".odt",
    ".rtf",
    ".wps",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".ods",
}


class OfficeRenderError(RuntimeError):
    """Raised when an Office source cannot be rendered safely."""


@dataclass(frozen=True)
class RenderedVisual:
    png: bytes
    locator: dict[str, Any]
    label: str


def _png_bytes(image: Any) -> bytes:
    if isinstance(image, (bytes, bytearray, memoryview)):
        image = Image.open(io.BytesIO(bytes(image)))
    if not isinstance(image, Image.Image):
        raise TypeError("Expected a PIL image or encoded image bytes")
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def _source_pages(chunk: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for value in chunk.get("page_num_int") or []:
        try:
            page = int(value)
        except (TypeError, ValueError):
            continue
        if page > 0 and page not in pages:
            pages.append(page)
    for position in chunk.get("position_int") or []:
        if not isinstance(position, (list, tuple)) or not position:
            continue
        try:
            page = int(position[0])
        except (TypeError, ValueError):
            continue
        if page > 0 and page not in pages:
            pages.append(page)
    return pages


def _base_locator(
    filename: str,
    chunk: dict[str, Any],
    chunk_index: int,
    source_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    locator: dict[str, Any] = {
        "filename": Path(filename).name,
        "chunk_index": chunk_index,
    }
    locator.update({key: value for key, value in (source_identity or {}).items() if value is not None})
    if chunk.get("position_int") is not None:
        locator["positions"] = chunk["position_int"]
    for key in ("doc_id", "dataset_id", "location", "sha256"):
        if chunk.get(key) is not None:
            locator[key] = chunk[key]
    return locator


def _render_pdf_pages(binary: bytes, pages: list[int]) -> list[RenderedVisual]:
    import pdfplumber

    result: list[RenderedVisual] = []
    with pdfplumber.open(io.BytesIO(binary)) as pdf:
        for page_number in pages:
            if page_number < 1 or page_number > len(pdf.pages):
                raise ValueError(f"PDF page {page_number} is outside the source document (1-{len(pdf.pages)})")
            image = pdf.pages[page_number - 1].to_image(resolution=144).annotated
            result.append(RenderedVisual(_png_bytes(image), {"source_type": "pdf", "page": page_number}, f"Page {page_number}"))
    return result


def spreadsheet_pdf_fallback_chunks(filename: str, binary: bytes, lang: str) -> list[dict[str, Any]]:
    """Render a failed spreadsheet parse into page chunks for multimodal recovery."""
    import pdfplumber
    from rag.nlp import rag_tokenizer, tokenize

    pdf = convert_office_to_pdf(filename, binary)
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        page_numbers = list(range(1, len(document.pages) + 1))
    if not page_numbers:
        raise OfficeRenderError("LibreOffice produced an empty PDF for the spreadsheet")
    visuals = _render_pdf_pages(pdf, page_numbers)
    chunks: list[dict[str, Any]] = []
    for page_number, visual in zip(page_numbers, visuals, strict=True):
        image = Image.open(io.BytesIO(visual.png)).convert("RGB")
        chunk: dict[str, Any] = {
            "docnm_kwd": filename,
            "title_tks": rag_tokenizer.tokenize(Path(filename).stem),
            "doc_type_kwd": "spreadsheet",
            "image": image,
            "page_num_int": [page_number],
            "position_int": [[page_number, 0, image.width, 0, image.height]],
            "_spreadsheet_pdf_fallback": True,
            "_multimodal_force": True,
        }
        tokenize(
            chunk,
            f"[Spreadsheet table parser failed; rendered page {page_number} requires multimodal recovery]",
            lang.lower() == "english",
            language=lang,
        )
        chunks.append(chunk)
    return chunks


def _cached_pdf_pages(
    binary: bytes,
    pages: list[int],
    render_cache: dict[str, Any] | None,
    cache_key: str,
) -> list[RenderedVisual]:
    if render_cache is None:
        return _render_pdf_pages(binary, pages)
    page_caches = render_cache.setdefault("pdf_pages", {})
    page_cache = page_caches.setdefault(cache_key, {})
    missing = [page for page in pages if page not in page_cache]
    for rendered in _render_pdf_pages(binary, missing) if missing else []:
        page_cache[rendered.locator["page"]] = rendered
    return [page_cache[page] for page in pages]


def convert_office_to_pdf(filename: str, binary: bytes) -> bytes:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        raise OfficeRenderError("LibreOffice is required to render Office documents for multimodal parsing")
    suffix = Path(filename).suffix.lower()
    if suffix not in PAGED_OFFICE_EXTENSIONS:
        raise OfficeRenderError(f"LibreOffice rendering is not enabled for {suffix or 'files without an extension'}")
    timeout = max(10, int(os.getenv("RAGFLOW_OFFICE_RENDER_TIMEOUT", "120")))
    with tempfile.TemporaryDirectory(prefix="ragflow-office-render-") as root:
        root_path = Path(root)
        source = root_path / ("source" + suffix)
        output = root_path / "output"
        profile = root_path / "profile"
        output.mkdir()
        profile.mkdir()
        source.write_bytes(binary)
        command = [
            executable,
            "--headless",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output),
            str(source),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, check=False, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise OfficeRenderError(f"LibreOffice timed out after {timeout}s while rendering {suffix}") from exc
        pdfs = list(output.glob("*.pdf"))
        if completed.returncode != 0 or len(pdfs) != 1:
            raise OfficeRenderError(f"LibreOffice could not render {suffix}; verify that the file is valid and not password protected")
        return pdfs[0].read_bytes()


def _chunk_text(chunk: dict[str, Any]) -> str:
    for key in ("content_with_weight", "text", "question_kwd"):
        value = chunk.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            return "\n".join(str(item) for item in value)
    tokens = chunk.get("content_ltks")
    if isinstance(tokens, str) and tokens.strip():
        return tokens.strip()
    return "[No textual preview is available for this chunk]"


def _font(size: int = 24):
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_canvas(text: str, title: str) -> bytes:
    width, margin = 1600, 48
    font = _font()
    title_font = _font(28)
    # Character wrapping is deterministic and works for CJK text without spaces.
    normalized = text.replace("\t", "    ")
    lines: list[str] = []
    for raw_line in normalized.splitlines() or [""]:
        while len(raw_line) > 92:
            lines.append(raw_line[:92])
            raw_line = raw_line[92:]
        lines.append(raw_line)
    lines = lines[:240]
    line_height = 34
    height = min(9000, margin * 2 + 60 + max(1, len(lines)) * line_height)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((margin, margin), title, fill="#1f2937", font=title_font)
    y = margin + 60
    for line in lines:
        draw.text((margin, y), line, fill="black", font=font)
        y += line_height
    return _png_bytes(image)


def _text_locator(
    filename: str,
    chunk: dict[str, Any],
    chunk_index: int,
    source_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    locator = _base_locator(filename, chunk, chunk_index, source_identity)
    locator["source_type"] = "text"
    if chunk.get("source_line_start_int") is not None:
        locator["line_start"] = chunk["source_line_start_int"]
    if chunk.get("source_line_end_int") is not None:
        locator["line_end"] = chunk["source_line_end_int"]
    return locator


def render_chunk_visuals(
    filename: str,
    binary: bytes,
    chunk: dict[str, Any],
    chunk_index: int,
    source_identity: dict[str, Any] | None = None,
    render_cache: dict[str, Any] | None = None,
) -> list[RenderedVisual]:
    """Return ordered visual inputs without mutating *chunk*."""
    extension = Path(filename).suffix.lower()
    pages = _source_pages(chunk)
    base = _base_locator(filename, chunk, chunk_index, source_identity)

    image = chunk.get("image")
    if isinstance(image, (Image.Image, bytes, bytearray, memoryview)):
        spreadsheet_fallback = bool(chunk.get("_spreadsheet_pdf_fallback"))
        source_type = "spreadsheet" if spreadsheet_fallback else "image" if extension in IMAGE_EXTENSIONS else "pdf" if extension == ".pdf" else "chunk"
        locator = {**base, "source_type": source_type}
        if pages:
            locator["page"] = pages[0]
        if spreadsheet_fallback and pages:
            locator["rendered_page"] = pages[0]
            locator["fallback_reason"] = "table_parse_failed"
        return [RenderedVisual(_png_bytes(image), locator, f"Source {pages[0]}" if pages else f"Chunk {chunk_index + 1}")]

    if extension in IMAGE_EXTENSIONS:
        source = Image.open(io.BytesIO(binary))
        source.load()
        locator = {**base, "source_type": "image", "pixel_bounds": [0, 0, source.width, source.height]}
        return [RenderedVisual(_png_bytes(source), locator, "Original image")]

    if extension == ".pdf" and pages:
        rendered = _cached_pdf_pages(binary, pages, render_cache, "source")
        return [RenderedVisual(item.png, {**base, **item.locator}, item.label) for item in rendered]

    # Spreadsheet parser positions identify rows/cells rather than rendered PDF
    # pages.  Treating the first position value as a page can request a page that
    # does not exist.  The table parser output is instead rendered as a stable
    # text canvas while the original row/cell positions remain in the locator.
    if extension in PAGED_OFFICE_EXTENSIONS - SPREADSHEET_EXTENSIONS and pages:
        if render_cache is not None and "office_pdf" in render_cache:
            pdf = render_cache["office_pdf"]
        else:
            pdf = convert_office_to_pdf(filename, binary)
            if render_cache is not None:
                render_cache["office_pdf"] = pdf
        rendered = _cached_pdf_pages(pdf, pages, render_cache, "office")
        if extension in PRESENTATION_EXTENSIONS:
            return [
                RenderedVisual(
                    item.png,
                    {**base, "source_type": "presentation", "slide": item.locator["page"], "rendered_page": item.locator["page"]},
                    f"Slide {item.locator['page']}",
                )
                for item in rendered
            ]
        return [
            RenderedVisual(
                item.png,
                {**base, "source_type": "office", "rendered_page": item.locator["page"]},
                f"Rendered page {item.locator['page']}",
            )
            for item in rendered
        ]

    locator = _text_locator(filename, chunk, chunk_index, source_identity)
    text = _chunk_text(chunk)
    return [RenderedVisual(_text_canvas(text, f"{Path(filename).name} · chunk {chunk_index + 1}"), locator, f"Chunk {chunk_index + 1}")]
