# Universal Multimodal Source Rendering Design

## Goal

Make every built-in chunking method capable of using chunk-mm whenever its input file type can be parsed, while preserving citations to the original file and the original location inside that file.

## Root cause

The current chunk-mm post-processor assumes every chunk contains a PIL image in `chunk["image"]`. That is true for some PDF parser paths, but false for Presentation on PPT/PPTX and for several text, Office, spreadsheet, and email paths. Those chunks fail with `Multimodal parsing requires an actual Chunk screenshot` even though the dataset and document forms allow multimodal parsing.

## Architecture

Chunking and visual rendering are separate responsibilities:

1. The selected parser continues to define chunk boundaries.
2. A shared visual-source renderer obtains one or more images for each chunk.
3. Images are mapped back to the original file through a stable source locator.
4. The vision model replaces only the searchable text fields. Existing document identity and position fields remain unchanged.

The renderer uses this priority order:

1. Reuse a valid image already attached to the chunk.
2. Render referenced pages directly from a PDF.
3. Convert presentation and paged Office formats to a temporary PDF with headless LibreOffice, then render the mapped pages.
4. When an Office or spreadsheet parser does not expose a stable rendered-page locator, render the parser's Chunk text in a deterministic canvas rather than inventing a page/cell mapping.
5. Render HTML, Markdown, EPUB, email, plain text, code, JSON, XML, and similar parser output in the same deterministic Chunk canvas.
6. Use the source image directly for supported static image files.

Temporary PDFs and images are parsing artifacts. They never replace the source object and are never used to build a download URL.

## Source-location contract

Every multimodal chunk keeps the existing RAGFlow fields, including `doc_id`, `docnm_kwd`, `page_num_int`, `position_int`, and any source metadata supplied by the caller. The renderer also produces a locator that describes the original position:

- PDF: page number and original page coordinates.
- PPT/PPTX: slide number and, where available, shape identifiers.
- DOC/DOCX: rendered page when supplied by the base parser; otherwise Chunk index and original parser positions.
- XLS/XLSX/CSV: original parser positions and Chunk index; no cell range is invented when the base parser does not provide one.
- HTML/Markdown/EPUB: original parser positions and Chunk index.
- Text/code/JSON/XML: original line range.
- Image: original image and optional pixel bounds.
- Video/audio: time range; video uses frames and audio uses its ASR path rather than the vision renderer.

The durable archive manifest records the locator and the rendered-image hash. Search and MinIO URLs continue to use the original `dataset_id`, `location`, `sha256`, and `doc_id` values.

## Multi-page chunks

A chunk may reference more than one page. The renderer returns an ordered image list with page labels. The vision request sends multiple images in one message instead of shrinking them into one long image. The prompt states their original page or slide numbers.

## Office rendering

LibreOffice runs headlessly in an isolated temporary directory with a timeout. The production image installs LibreOffice and the existing Noto CJK fonts remain available. Conversion errors identify the source type and remediation in the task error. The original filename and bytes are never changed.

PPT/PPTX conversion is an internal rendering step. Slide `n` maps to converted PDF page `n`. For other Office formats, conversion is used only when the base parser supplies a stable page number. Otherwise the renderer uses a deterministic Chunk canvas because page breaks can vary with fonts and layout engines.

## Compatibility and failure behavior

Multimodal support does not broaden a parser's accepted file types. The UI must not imply that an incompatible parser/file pair is valid. For a valid pair, missing `chunk["image"]` is no longer a failure by itself; the shared renderer supplies the visual input or returns a precise unsupported-renderer error.

Parent/child splitting remains incompatible with screenshot replacement and continues to be rejected.

## Verification

Tests cover:

- Existing chunk images remain the first choice.
- Presentation PDF page rendering.
- PPT/PPTX conversion and slide-to-page mapping.
- Missing-image chunks fall back to source rendering.
- Plain-text rendering.
- Multiple source pages become multiple vision message images.
- Source identity and position fields are byte-for-byte unchanged after multimodal token replacement.
- The archive manifest contains original locators and rendered hashes.
- Missing LibreOffice and conversion failure produce actionable task errors.
- Representative built-in chunk methods can pass through the common multimodal post-processor without requiring parser-specific image fields.
