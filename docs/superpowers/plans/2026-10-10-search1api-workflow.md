# Search1API workflow implementation plan

**Goal:** Implement Python Search1API Search/Crawl workflow tools and record upstream/Python comparisons without changing custom retrieval or parsing behavior.

**Architecture:** Extend rag/utils/search1api_conn.py with strict raw search and crawl requests; new agent/tools/search1api.py follows automatic ToolBase discovery. Port the official frontend wiring selectively.

**Tech stack:** Python, requests, pytest; existing React forms, Jest and Vite.

## Constraints

- Preserve search(query), retrieve_chunks, Agentic APIs, full/smart parsing and worker namespaces.
- Fixed provider endpoints, bearer key only in config, sanitized errors, bounded results and timeouts.
- No production configuration changes; credentials are absent for live Search1API tests.

## Task 1: Connector and Python tools

- [x] Add failing tests in test/unit_test/agent/tools/test_search1api_workflow_unit.py for general/news defaults/overrides, invalid combinations, bounded counts, content fallback, raw output, references, crawl URL/object validation, missing credentials, sanitized failures, cancellation and metadata without credentials.
- [x] Run targeted pytest and verify missing behavior fails.
- [x] Add search_results(query, *, channel, search_service, time_range, max_results) and crawl(url) to Search1API, keeping old methods unchanged. Implement Search1APISearchParam/Search1APISearch and Search1APICrawlParam/Search1APICrawl with existing tool conventions.
- [x] Run new tests and existing test_search1api_port.py; verify both pass.

## Task 2: Frontend workflow surfaces

- [x] Add official tests for tool-name normalization and export sanitization; run and observe failure before wiring.
- [x] Add operators, defaults, node/forms/tool registration, icons and translations from #20666 without replacing shared Python adapters or UI primitives.
- [x] Add an integration registration test for both operators and a form test for service changes; verify Jest, formatting and production build in the existing isolated frontend workspace.

## Task 3: Compare and deliver

- [x] Enrich all 232 commit register rows with actual changed files and impact classification; individually compare key permissions, retries, embedding response counts, XLS, parser ranges, templates and citations to current Python owners.
- [x] Update dated inventory with exact observed matches and gaps; implement newly confirmed narrowly scoped defects with failing regression tests.
- [x] Run original Agentic/multimodal/template/parser/provider regression suites plus new tests; review diff, commit and push through authorized SSH route, verify remote tip.

## Execution ledger

- Initial ruling: continue in the user's existing chunk-mm checkout; no shared main edits or production changes. The authorized inventory is the scope; unknown items are audits, not an instruction to rewrite all Go infrastructure.

- Task 1 complete: 45 tool/connector regressions passed; old search contract preserved.
- Task 2 complete: 107 frontend regressions and Vite build passed. Existing unrelated navigation edits kept out of this change.
- Task 3 audit: 232 commit files registered, 22 priority comparisons (some partial), 13 docs-only and 197 semantic comparisons still pending. Two confirmed Python defects fixed with red/green tests; no claim of full upstream parity.
- Final delivery checks and push results are recorded in the dated feature inventory.
