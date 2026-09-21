# Mistral Agentic Search Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose all seven Mistral-style search tools on RAGFlow 9380 and register them in the DeepAgent repository.

**Architecture:** Reuse the current RAGFlow index, source-order reader, search and document services. Add a thin authenticated API and stateless tool service. Register five read-only tools by default; gate ingest/delete at both server and DeepAgent configuration.

**Tech Stack:** RAGFlow Quart, Python asyncio, RAGFlow retrieval/DB services, LangChain `@tool`, pytest.

## Global Constraints

- Preserve `/api/v1/agentic-search` and `/api/v1/agentic-search/stream`.
- `source_id` is document ID; offsets are zero-based visible chunk ordinals.
- `dataset_ids` is one comma-separated string.
- Authenticate and authorize on every tool call.
- Writes disabled by default; no unrestricted server-side URI fetch or local file read.
- Do not commit keys or tests that mutate production datasets.

---

### Task 1: Shared read-only service and schema

**Files:** `api/apps/services/agentic_search_tools_service.py`, `test/unit_test/api/apps/services/test_agentic_search_tools_service.py`.

- [ ] Write failing tests for per-tool input validation, output chunk fields, offset validation and authorization.
- [ ] Run the new unit tests and verify expected failures.
- [ ] Implement normalization and authorized context creation, using existing dataset router and `RAGTools` source reader.
- [ ] Run tests until green; commit this slice.

### Task 2: Search and navigation

**Files:** same service/tests; `api/apps/restful_apis/agentic_search_tools_api.py`, `test/testcases/restful_api/test_agentic_search_tools_routes_unit.py`.

- [ ] Write failing tests for search/exclude, open, navigate, read, grep, route authentication and error mapping.
- [ ] Implement all five read tools and POST routes under `/agentic-search/tools/`.
- [ ] Run focused tests, then commit.

### Task 3: Explicitly enabled ingest/delete

**Files:** tool service/routes/tests plus `README.agentic-search.md`.

- [ ] Write failing tests for default-off gate, URI restrictions, dataset ownership and single-document deletion.
- [ ] Implement guarded reuse of RAGFlow upload/parse/delete services.
- [ ] Verify tests and document configuration; commit.

### Task 4: DeepAgent adapters

**Files:** `est_knowledge_base/autonomous_flows/agentic_search/tools.py`, `autonomous_flows/configs/tool_catalog.yaml`, `controlled_flows/automated_loading/configs/node_catalog.yaml`, `tests/unit_tests/autonomous_flows/test_agentic_search_tool.py`, `README.md`.

- [ ] Write failing HTTP transport tests for all seven adapters and default registration of only five read tools.
- [ ] Implement independently callable async LangChain tools; keep existing one-shot tool for compatibility.
- [ ] Make ingest/delete available only through explicit DeepAgent configuration; run tests and commit.

### Task 5: Acceptance and push

- [ ] Run focused RAGFlow and DeepAgent tests and syntax checks.
- [ ] Query deployed 9380 read endpoints against the existing knowledge base only after this branch is deployed.
- [ ] Test write endpoints only in a dedicated test dataset when explicitly enabled.
- [ ] Push `chunk-mm` and `feat/fyc` using the user's SSH configuration; verify remote refs.
