# Python parity implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task in the current session.

**Goal:** Close verified Python gaps while retaining current custom behavior.

**Architecture:** Extend existing owning paths, opt in to new configurations, keep one Python runtime. Compare upstream behavior before implementation.

**Tech Stack:** Python, pytest, React/TypeScript, existing SDKs.

## Global constraints

Preserve custom features, independent queues and concurrent navigation edits. No production migrations or new infrastructure. Do not label untested provider behavior as accepted.

## Parser/storage

- [x] Add Docling tests for `do_ocr=False`, setup-over-environment precedence, absent defaults and all four protocol attempts in `test/unit_test/deepdoc/parser/test_docling_parser_remote.py`.
- [x] Run the tests red; extend `deepdoc/parser/docling_parser.py`, `rag/app/naive.py`, `rag/flow/parser/parser.py` to pass saved `docling_do_ocr`/`docling_pdf_backend` into all remote payloads.
- [x] Add UTF-8/16/32 BOM tests against actual `decode_text` and JSON/Markdown entry points; remove only the initial BOM in `rag/nlp/__init__.py`; verify ordinary and legacy-encoded text.
- [x] Compare Python S3/OSS SDK copy methods with upstream escaping change; record actual equivalence or reproduce defect before editing.

## Network tools

- [x] Compare actual MCP transport and token routes, add regression tests for confirmed differences, fix only those differences.

## Conversation/workflow

- [x] Compare configured model fallback, model resolution, tool binding, clone, streams and cancellation; add failure tests before implementation.
- [ ] Compare parser/Pipeline selection and workflow parameter/recovery changes, recording already equivalent paths separately.

## Task/Wiki/index

- [ ] Audit remaining inventory rows against Python owners, add reproduction tests for confirmed gaps and implement locally.

## Delivery

- [x] Run focused tests, original custom-feature suites and relevant frontend checks.
- [ ] Review staged diff, update comparison with exact evidence, commit and push only this work.


## Execution ledger / rulings

- Parser remote options, BOM, MCP, opt-in fallback, OSS, Wiki links, filters, Retrieval bindings/empty JSON and API Key UI implemented with observed failing regressions followed by passing tests.
- Ruling: retain the Python parser/Pipeline form and reparse confirmation while auditing the upstream UI replacement; the Go patch deletes Python-specific fields and cannot safely be applied wholesale. Unified picker remains pending.
- Ruling: retain Python API key backend behavior and apply the frontend 16-key control only; imposing a new server limit would change existing API clients.
- Ruling: final review's four findings fixed in this pass. Usage totals accumulate provider attempts; phase call count remains a logical request count.
- Ruling: external database/provider/runtime integration is unverified without its deployed service. No local mocked result is labeled live acceptance.
- Ruling: old Wiki fallback unit targeted removed synchronous orchestration. It now exercises the actual eligibility fallback owner, including disabled/deleted docs; generation has separate existing tests.
- Remaining broad inventory audits stay unchecked and are listed in section eight of the comparison report; this is not a declaration of full upstream parity.

- Final verification: Python 439 passed + 10 subtests, frontend 21 suites / 209 passed, final Vite production build 2m29s, TypeScript baseline 208 / added 0 / removed 0, added Python files Ruff clean.
