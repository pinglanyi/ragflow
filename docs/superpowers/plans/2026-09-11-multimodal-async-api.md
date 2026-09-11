# Multimodal Async API Implementation Plan

> Execute inline with executing-plans; use test-driven-development for each deliverable.

**Goal:** Two authenticated submission APIs and one durable document-job status API.

**Architecture:** Persist a MultimodalJob row, capture the exact child task IDs before queue publication, aggregate only those tasks, and snapshot terminal states before native task deletion. Reuse existing storage, queue, screenshot parser and embedding workers.

**Tech Stack:** Quart, Peewee, existing database and Redis queue, Python unittest with SQLite for isolated persistence tests.

## Global Constraints

- Work in the user-selected chunk-mm checkout. Preserve unrelated files.
- No model calls in request/status handlers. Upload transmission and queue preparation are synchronous; parsing is not.
- API key authorization and tenant ownership required. No raw model URL/key overrides.
- Never report complete from document-global status alone. Preserve terminal state across reruns.
- Use current database table discovery; no dependency changes to production.

## Task 1: Durable state and configuration

- [x] Add failing tests in `test/unit_test/test_multimodal_jobs.py` for configuration type validation, inheritance, empty output, partial success, cancellation, ownership and dispatch state.
- [x] Run `python test/unit_test/test_multimodal_jobs.py -v` and confirm missing implementation fails.
- [x] Add `MultimodalJob` in `api/db/db_models.py`; implement `api/db/services/multimodal_job_service.py` with `build_config`, `refresh`, `bind_tasks`, `mark_dispatched`, `before_delete`, and `prepare_task`.
- [x] Re-run tests using a SQLite-bound extraction of the real model and service (external RAGFlow services stubbed).

## Task 2: Submission and worker integration

- [x] Test `submit(tenant_id, dataset_id, document_id, options)` rejects busy/pipeline documents and invalid vision models before mutation; records failed dispatch.
- [x] Implement `api/apps/services/multimodal_api_service.py` and thin `api/apps/restful_apis/multimodal_api.py` routes.
- [x] Bind child IDs inside `queue_tasks` before enqueue; mark dispatched only after all queue writes succeed. Hook worker task loading and progress, and native task deletion.
- [x] Add Quart test-client checks for both POST bodies, 202, 400, 404, 409 and GET results. Run combined tests.

## Task 3: Documentation and verification

- [x] Update `docs/chunk-multimodal-api.md` with exact custom routes, curl requests and failure/restart semantics.
- [x] Run focused tests, existing multimodal regression tests, Python compilation and diff whitespace checks.
- [x] Review critical races and authorization paths; explicitly report that live GPU/server acceptance remains untested locally.

## Verification record

2026-09-11: 38 new SQLite/Quart contract tests, 18 archive tests, 8 model/OCR tests and 6 launcher tests pass (70 total). Tests run with isolated Peewee 3.19.0 (within production requirement) and Quart; no production dependency pins changed. New Python files pass Ruff; all changed production Python files compile. Read-only review findings addressed with terminal CAS, unique active document claims, counter cleanup, failure recovery, conditional worker claims and storage write fencing in both executors. MySQL/PostgreSQL advisory locks, Redis and real GPU/model API remain server acceptance items.
