# Stateless Agentic Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let callers invoke `POST /api/v1/agentic-search` with a query and dataset IDs, without creating or supplying a Chat Assistant ID.

**Architecture:** Extend request validation with two explicit modes. Stateful mode keeps the existing persisted Chat Assistant/session path; stateless mode builds an in-memory dialog and conversation, resolves the tenant default model when needed, calls the same non-streaming `rag_agent`, and persists nothing.

**Tech Stack:** Python, Quart, RAGFlow Peewee services, pytest, PowerShell, Bash/curl/jq.

## Global Constraints

- Stateless mode requires at least one accessible, parsed dataset.
- `session_id` is invalid without `chat_id`.
- Stateless mode creates no Dialog or Conversation database rows.
- Existing stateful requests remain compatible.
- Bearer tokens and provider keys never enter logs or committed files.

---

### Task 1: Stateless request contract and temporary objects

**Files:**
- Modify: `api/apps/services/agentic_search_api_service.py`
- Modify: `test/unit_test/api/apps/services/test_agentic_search_api_service.py`

**Interfaces:**
- Produces: `validate_agentic_search_request(payload: dict) -> dict` accepting either `chat_id` or non-empty `dataset_ids`.
- Produces: `build_stateless_dialog(*, tenant_id: str, dataset_ids: list[str], model: str, options: dict)`.
- Produces: `build_stateless_conversation()` returning an in-memory conversation compatible with `structure_answer`.

- [ ] **Step 1: Write failing request-mode tests**

Add tests asserting `query + dataset_ids` succeeds without `chat_id`, missing both fails, `session_id` without `chat_id` fails, and the temporary dialog contains the tenant, datasets, model, knowledge prompt, and request overrides.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py -q
```

Expected: failures because validation still requires `chat_id` and temporary builders do not exist.

- [ ] **Step 3: Implement validation and temporary builders**

Change validation to require `chat_id` or a non-empty normalized `dataset_ids`. Reject `session_id` without `chat_id`. Add temporary dialog defaults equivalent to the knowledge-enabled Chat Assistant defaults and an in-memory conversation object with `message`, `reference`, and `to_dict` support.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 command and expect all tests to pass.

- [ ] **Step 5: Commit**

```bash
git add api/apps/services/agentic_search_api_service.py test/unit_test/api/apps/services/test_agentic_search_api_service.py
git commit -m "feat: add stateless agentic search contract"
```

### Task 2: Stateless execution path

**Files:**
- Modify: `api/apps/services/agentic_search_api_service.py`
- Modify: `test/unit_test/api/apps/services/test_agentic_search_api_service.py`
- Modify: `test/testcases/restful_api/test_agentic_search_routes_unit.py`

**Interfaces:**
- Consumes: the validated mode and temporary builders from Task 1.
- Produces: `execute_agentic_search` returning normalized results with nullable `chat_id` and `session_id`.

- [ ] **Step 1: Write a failing stateless execution test**

Stub tenant default model resolution, dataset authorization, `rag_agent`, and persistence services. Assert the result has `chat_id is None`, `session_id is None`, contains references, uses the requested datasets, and never calls Dialog or Conversation save/update methods.

- [ ] **Step 2: Run the test and verify RED**

Run the focused service test and expect failure because execution indexes `options["chat_id"]` and queries DialogService.

- [ ] **Step 3: Implement execution branching**

Validate datasets before branching. In stateful mode retain existing dialog/session behavior. In stateless mode resolve the explicit model or `get_tenant_default_model_by_type`, build temporary objects, skip all persistence, and normalize nullable IDs.

- [ ] **Step 4: Verify service and route tests**

```bash
python -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py -q
```

Expected: all tests pass, including existing stateful coverage.

- [ ] **Step 5: Commit**

```bash
git add api/apps/services/agentic_search_api_service.py test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py
git commit -m "feat: execute agentic search without chat id"
```

### Task 3: DeepAgent usage, scripts, and final verification

**Files:**
- Modify: `scripts/test_agentic_search.ps1`
- Modify: `scripts/test_agentic_search.sh`
- Modify: `test/unit_test/test_agentic_search_scripts.py`
- Modify: `README.agentic-search.md`

**Interfaces:**
- Produces: one-click stateless calls with optional `chat_id`.
- Documents: direct curl and Python calls requiring only API key, query, and dataset IDs.

- [ ] **Step 1: Write failing script contract tests**

Assert neither script assigns the previous test Chat ID as a default, each omits `chat_id` when empty, and each still accepts an optional Chat ID for compatibility.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest --noconftest test/unit_test/test_agentic_search_scripts.py -q
```

Expected: failures because both scripts currently default to a concrete Chat ID and always send it.

- [ ] **Step 3: Update scripts and README**

Make `ChatId`/`--chat-id` optional and conditionally add it to the JSON body. Lead README usage with stateless DeepAgent examples, explain that `dataset_ids` replace Chat Assistant scope, and retain stateful session continuation as an optional mode.

- [ ] **Step 4: Run final checks**

```bash
python -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py test/unit_test/test_agentic_search_scripts.py test/agentic_search -q
bash -n scripts/test_agentic_search.sh
python -m py_compile api/apps/restful_apis/agentic_search_api.py api/apps/services/agentic_search_api_service.py
git diff --check
```

Also parse `scripts/test_agentic_search.ps1` with the PowerShell language parser. Expected: all tests and syntax checks pass.

- [ ] **Step 5: Commit and push**

```bash
git add README.agentic-search.md scripts/test_agentic_search.ps1 scripts/test_agentic_search.sh test/unit_test/test_agentic_search_scripts.py
git commit -m "docs: document stateless agentic search calls"
git push origin chunk-mm
```
