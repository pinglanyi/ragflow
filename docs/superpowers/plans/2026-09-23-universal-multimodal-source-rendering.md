# Universal Multimodal Source Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chunk-mm work with every valid built-in chunk method by rendering visual input from the source file while retaining original-file citations.

**Architecture:** Add a renderer independent of the parser and call it from the shared chunk-mm post-processor whenever a chunk has no usable image. Return ordered rendered images plus original-source locators, send multi-page chunks as multi-image vision requests, and archive the mapping without changing RAGFlow's existing citation fields.

**Tech Stack:** Python 3.13, Pillow, pdfplumber, python-pptx, LibreOffice headless, pytest/unittest, Docker.

## Global Constraints

- Temporary render artifacts must never replace or rename the original object.
- Preserve all existing chunk identity, metadata, page, and position fields.
- Use the parser's chunk boundaries; the renderer must not rechunk content.
- Parent/child chunking remains rejected when chunk-mm is enabled.
- A valid parser/file pair must not fail solely because the parser omitted `chunk["image"]`.
- Errors must name the renderer and corrective action without exposing credentials or storage URLs.

---

### Task 1: Source visual renderer and locator contract

**Files:**
- Create: `rag/svr/multimodal_source_renderer.py`
- Test: `test/unit_test/test_multimodal_source_renderer.py`

**Interfaces:**
- Produces: `render_chunk_visuals(filename, binary, chunk, chunk_index) -> list[RenderedVisual]`
- Produces: `RenderedVisual.png: bytes`, `RenderedVisual.locator: dict`

- [ ] Write failing tests for attached images, PDF page rendering, plain-text fallback, and preservation-oriented locators.
- [ ] Run `uv run pytest test/unit_test/test_multimodal_source_renderer.py -q` and confirm the missing module/API failures.
- [ ] Implement immutable rendered-visual values, page extraction from existing position fields, PDF rendering through pdfplumber, source-image loading, and deterministic text canvas rendering.
- [ ] Run the renderer tests and confirm they pass.

### Task 2: Office presentation conversion

**Files:**
- Modify: `rag/svr/multimodal_source_renderer.py`
- Modify: `Dockerfile`
- Test: `test/unit_test/test_multimodal_source_renderer.py`

**Interfaces:**
- Produces: `convert_office_to_pdf(filename, binary) -> bytes`
- Consumes: `render_chunk_visuals(...)` from Task 1.

- [ ] Add failing tests with a fake `soffice` executable for slide mapping, timeout, missing executable, and conversion failure.
- [ ] Run the focused tests and confirm they fail for the missing converter.
- [ ] Implement isolated temporary conversion, strict filename sanitization, timeout, and slide/page mapping.
- [ ] Add LibreOffice packages to the Ubuntu production base image.
- [ ] Run focused tests and confirm they pass.

### Task 3: Multi-image inference and durable source mapping

**Files:**
- Modify: `rag/svr/chunk_multimodal.py`
- Test: `test/unit_test/test_chunk_multimodal_archive.py`

**Interfaces:**
- Consumes: `render_chunk_visuals(...)`.
- Changes: `ScreenshotParser.parse` accepts ordered rendered visuals and archives their locators.

- [ ] Add failing tests proving a chunk without `image` uses the source renderer, multiple pages create multiple image message parts, and original chunk fields remain unchanged.
- [ ] Run the focused tests and confirm the old `actual Chunk screenshot` failure.
- [ ] Update cache keys, request messages, archive manifests, progress, and token replacement for ordered visuals.
- [ ] Ensure only text/token fields and `_multimodal_image_sha256` change; copy locator data into the archive rather than overwriting `position_int`.
- [ ] Run focused tests and confirm they pass.

### Task 4: Parser matrix and task error behavior

**Files:**
- Modify: `test/unit_test/test_chunk_multimodal_archive.py`
- Modify: `test/unit_test/test_multimodal_jobs.py`
- Modify: `web/src/components/multimodal-parser-options.tsx`

**Interfaces:**
- Consumes: shared source renderer and existing task progress callbacks.

- [ ] Add parameterized tests representing chunks from all built-in parser IDs with and without attached images.
- [ ] Verify each valid parser output reaches multimodal inference and retains source positions.
- [ ] Update UI guidance to explain source rendering, Office conversion, locator retention, and media-specific behavior.
- [ ] Verify missing renderer dependencies appear in task failure messages.

### Task 5: Regression, integration, and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-09-23-universal-multimodal-source-rendering-design.md` only if verified implementation details differ.

**Interfaces:**
- Validates the completed pipeline.

- [ ] Run focused Python unit tests.
- [ ] Run the existing multimodal API/job suites.
- [ ] Run frontend lint/type/tests covering the changed component.
- [ ] Parse a representative PDF and PPTX with Presentation plus chunk-mm against the local deployment when LibreOffice is available.
- [ ] Confirm the resulting chunks retain original document IDs and page/slide positions.
- [ ] Run `git diff --check`, review the final diff, and commit the verified implementation.

