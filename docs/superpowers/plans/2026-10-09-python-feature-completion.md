# Python feature completion implementation plan

> Execute the user's approved full inventory on `chunk-mm`; use separate commits and review each independently testable change.

**Goal:** Finish the remaining Python ports while preserving custom Agentic Search, full/smart parsing, model bindings and editable templates.

**Architecture:** Extend current owning services and parser/tool entry points. New provider configuration is opt-in. New vision settings inherit old behavior when absent. Index enrichment adds declared title terms without changing content, file names or vectors. No Go backend merge or database migration.

**Tech stack:** Existing Python services, React forms, pytest, Jest and Ruff.

## 1. Declared title indexing

Files: new `rag/nlp/declared_title.py`, `rag/svr/task_executor_refactor/chunk_service.py`, new focused unit tests.

- [x] Write/run failing tests: first nonempty chunk's first 20 lines; title/name/fullname; Chinese text; numeric/label noise; bounded/deduplicated tokens; existing title/filename/content/vector preservation; no header no-op.
- [x] Implement bounded extraction and append title terms after final parsing, including table recovery, before embedding/index writes.
- [x] Test the actual chunk-builder hook with isolated parser services, lint and review, then commit.

## 2. grep/BM25 contracts

Files: `rag/advanced_rag/harness/tools/search.py`, focused search unit tests.

- [x] Compare official `2400ca8eb` with current Python: keyword-only retrieval, no dense fallback, ordinary available chunks, compiled products excluded, scoped/empty selection behavior.
- [x] Write failing tests for actual gaps, then repair the current BM25 owner path; do not change literal regex boundary semantics or whole-table preservation merely to imitate Go optimization.
- [x] Verify existing grep/narrowing and original API tests, review and commit any fix; document already-present pieces.

## 3. Stable web evidence

Files: new `rag/utils/web_evidence.py`, existing four web connectors, new tests.

- [x] Fail tests for repeated results across calls, reorderings, distinct URL/content, Unicode, duplicate suppression, aggregate/handle alignment and input immutability.
- [x] Normalize web connector outputs to deterministic source/document and content/chunk IDs; preserve text, URL, score and result order.
- [x] Verify actual connector output paths plus existing connector regressions, review and commit.

## 4. Global vision and page ranges

Files: `rag/flow/parser` implementation/tests, parser form adapter/components, affected Python validation only if necessary.

- [x] Compare upstream `e8f7f9723` and `6c3217240`; test default old behavior, explicit enhancement on/off, global model selection and page limits.
- [x] Add opt-in global control through existing flow parser configuration; preserve family settings and custom full/smart parser paths.
- [x] Persist frontend controls using existing backend adapter conventions; validate Python parsing, UI forms, default behavior and page boundaries, review then commit.

## 5. Providers

Files: `rag/utils/search1api_conn.py`, web provider factory/form/types, `rag/llm` registration, `conf/llm_factories.json`, related tests.

- [x] Test Search1API selection/key validation/request/result shape/failures, then wire factory plus frontend provider choice and key persistence.
- [x] Test Opper discovery and supported chat/vision/embedding calls, implement current Python interfaces and Python factory catalog.
- [x] Compare SiliconFlow catalogs and add supported missing models to the catalog actually loaded by Python, retaining existing entries.
- [x] Verify configured providers are discoverable and old providers remain usable; no live credential or binding changes. Review then commit.

## 6. Delivery

- [x] Run combined original and new targeted regression tests, touched UI tests/build and added-line lint checks; distinguish existing baseline findings.
- [x] Update the inventory with implementation evidence, enablement paths and deployment/reparse requirements.
- [x] Push all reviewed commits through the user's SSH configuration and verify the remote branch tip.
- [x] Leave online acceptance explicitly pending deployment; do not claim external model/GPU success from isolated unit tests.

Evidence: Python 231 passed; legacy search connectors 10 passed; frontend expanded regression 81 passed / 5 unchanged baseline failures; production build exit 0; TypeScript final and baseline both contain the same 208 diagnostics. Online acceptance remains pending deployment. See the dated test report.
