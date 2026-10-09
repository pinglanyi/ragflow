# Python metadata selector implementation plan

> Execute sequentially in the current authorized `chunk-mm` branch. The user approved implementation, testing and push, and requires a feature summary before each subsequent port.

**Goal:** Select authorized documents by real metadata without invoking embeddings, expose this through the existing Python Agentic Search API and agent tool, and preserve query-based retrieval.

**Architecture:** A shared selector owns validation, scoped metadata resolution and bounded output. HTTP resolves user access before selection; the harness supplies its already-authorized dataset and document scopes. Existing query retrieval consumes the selected IDs with compiled expansion disabled.

**Tech stack:** Python, existing Quart API, DocMetadataService, DocumentService, pytest.

## Constraints

- No model/credential changes or schema migration.
- Preserve existing tools and query-based metadata retrieval.
- Empty matches never widen scope; infrastructure failure is distinct from no matches.
- At most 10 conditions, 200 returned documents and 60,000 output characters; identify truncation.
- Every implementation commit must pass focused tests and receive review before push.

## Task 1: Shared selector

Files: create `rag/advanced_rag/harness/tools/metadata.py`; extend strict read error propagation in `api/db/services/doc_metadata_service.py`; tests in `test/unit_test/rag/advanced_rag/test_metadata_selector_unit.py`.

- [x] Write failing tests for validation, arbitrary real fields, metadata-only selection, empty matches, session scope, invalid IDs, cross-dataset stale hits, truncation, and infrastructure failures.
- [x] Run isolated pytest and verify failures describe missing selector behavior.
- [x] Implement `validate_metadata_filters(filters, logic)` and `select_metadata_documents(kb_ids, filters, logic='and', *, doc_scope=None, limit=50)` with lazy service imports.
- [x] Query each dataset separately to preserve tenant boundaries. Resolve valid document records before reading their metadata. Never pass empty IDs to an API where empty means all.
- [x] Add opt-in strict metadata reads; existing callers retain existing defaults.
- [x] Run selector tests to green.

## Task 2: Agent and API wiring

Files: `api/apps/services/agentic_search_tools_service.py`, `rag/advanced_rag/harness/action_session.py`, `rag/prompts/action_run.md`; related service/schema/route tests.

- [x] Test `execute_tool('metadata_search', {'dataset_ids':'kb', 'filters':[{'key':'year','op':'=','value':'2026'}]}, user_id='user')` without initializing an embedding model.
- [x] Extend the existing HTTP tool validator and read dispatch to use the shared selector after authorization.
- [x] Make harness metadata query optional and allow real field names. No query returns document IDs and metadata; a query still retrieves chunks within those IDs.
- [x] Preserve document handles for later read/search calls and update the tool playbook.
- [x] Run original Agentic Search API and tools regression tests plus new harness tests.

## Task 3: Review and delivery

- [x] Document the feature inventory, API example, result bounds and deployment status.
- [x] Run focused selector, harness, routes, search, multimodal and template tests; lint touched Python files.
- [x] Review actual caller paths for scope widening and misleading empty results; address findings and rerun affected checks.
- [ ] Commit this feature independently and push using the configured SSH transport.
- [ ] Verify online after deployment. Local regression: 163 passed; online acceptance remains pending deployment.
