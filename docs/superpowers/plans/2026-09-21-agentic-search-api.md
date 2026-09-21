# Agentic Search HTTP API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stable `POST /api/v1/agentic-search` endpoint to the existing 9380 API server and update the smoke-test scripts to exercise it.

**Architecture:** A focused service module validates request options, creates a request-scoped copy of the authorized dialog, and normalizes the final answer and citations. A thin Quart route handles authentication and request parsing, then delegates to the service without mutating stored Chat Assistant configuration.

**Tech Stack:** Python 3.13, Quart, Peewee-backed RAGFlow services, pytest, PowerShell, Bash/curl/jq.

## Global Constraints

- Run inside the existing 9380 Quart API application.
- Reuse existing bearer-token authentication, tenant authorization, model resolution, `rag_agent`, and session persistence.
- Never persist request-scoped `dataset_ids`, `model`, `top_n`, or `similarity_threshold` overrides to the Chat Assistant.
- Return non-streaming plain JSON suitable for a future MCP tool.
- Never log bearer tokens or provider API keys.

---

### Task 1: Request contract and response normalization

**Files:**
- Create: `api/apps/services/agentic_search_api_service.py`
- Test: `test/unit_test/api/apps/services/test_agentic_search_api_service.py`

**Interfaces:**
- Produces: `validate_agentic_search_request(payload: dict) -> dict`
- Produces: `normalize_agentic_search_result(result: dict, *, request_id: str, model: str, reasoning: int, elapsed_ms: int) -> dict`
- Produces: `apply_dialog_overrides(dialog, options: dict)` returning a deep-copied dialog.

- [ ] **Step 1: Write failing validation and immutability tests**

```python
def test_validate_requires_query_and_chat_id():
    with pytest.raises(ValueError, match="query"):
        validate_agentic_search_request({"chat_id": "chat-1"})

def test_apply_dialog_overrides_does_not_mutate_source():
    source = SimpleNamespace(kb_ids=["a"], llm_id="old", top_n=8, similarity_threshold=0.2)
    copied = apply_dialog_overrides(source, {"dataset_ids": ["b"], "model": "new", "top_n": 3})
    assert source.kb_ids == ["a"]
    assert copied.kb_ids == ["b"]
    assert copied.llm_id == "new"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest test/unit_test/api/apps/services/test_agentic_search_api_service.py -q`

Expected: collection/import failure because the service module does not exist.

- [ ] **Step 3: Implement validation, immutable overrides, and normalization**

Validation accepts only `query`, `chat_id`, `session_id`, `dataset_ids`, `model`, `reasoning`, `top_n`, and `similarity_threshold`; strips the query; enforces reasoning 1..4; and rejects unknown fields. Normalization maps `reference.chunks` into stable reference records containing chunk, dataset, document, content, similarity, positions, image and URL fields.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `uv run pytest test/unit_test/api/apps/services/test_agentic_search_api_service.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/apps/services/agentic_search_api_service.py test/unit_test/api/apps/services/test_agentic_search_api_service.py
git commit -m "feat: add agentic search API contract"
```

### Task 2: Authenticated 9380 route and execution path

**Files:**
- Create: `api/apps/restful_apis/agentic_search_api.py`
- Modify: `api/apps/services/agentic_search_api_service.py`
- Test: `test/testcases/restful_api/test_agentic_search_routes_unit.py`

**Interfaces:**
- Consumes: Task 1 validation and normalization helpers.
- Produces: `POST /api/v1/agentic-search`.
- Produces: `execute_agentic_search(*, tenant_id: str, options: dict) -> dict`.

- [ ] **Step 1: Write failing route tests**

Tests load the route module with a stub request and monkeypatch the execution service. They assert missing query is rejected, the authenticated tenant ID reaches the service, successful data uses the existing response envelope, and the route is declared at `/agentic-search`.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest test/testcases/restful_api/test_agentic_search_routes_unit.py -q`

Expected: import failure because the route module does not exist.

- [ ] **Step 3: Implement request-scoped execution**

Load the owned dialog, validate optional dataset access, validate the optional model through `resolve_model_config`, create or validate the conversation, deep-copy the dialog, apply overrides, and consume `rag_agent(..., stream=False, reasoning=reasoning)` until the final result. Persist conversation messages through existing services, normalize the final result, and log the generated request ID and elapsed time.

- [ ] **Step 4: Register the Quart route**

```python
@manager.route("/agentic-search", methods=["POST"])
@login_required
async def agentic_search():
    payload = await get_request_json()
    options = validate_agentic_search_request(payload)
    data = await execute_agentic_search(tenant_id=current_user.id, options=options)
    return get_json_result(data=data)
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `uv run pytest test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add api/apps/restful_apis/agentic_search_api.py api/apps/services/agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py
git commit -m "feat: expose agentic search API"
```

### Task 3: One-click scripts, documentation, and live verification

**Files:**
- Create: `scripts/test_agentic_search.ps1`
- Create: `scripts/test_agentic_search.sh`
- Modify: `README.agentic-search.md`
- Test: `test/unit_test/test_agentic_search_scripts.py`

**Interfaces:**
- Consumes: `POST /api/v1/agentic-search`.
- Produces: parameterized PowerShell and Bash commands with JSONL request/response logs.

- [ ] **Step 1: Write failing script contract tests**

Tests assert both scripts target `/api/v1/agentic-search`, accept query/base URL/API key/chat/dataset/model/reasoning/log arguments, redact the API key, and do not PATCH `/api/v1/chats`.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest test/unit_test/test_agentic_search_scripts.py -q`

Expected: failure because scripts are absent from this worktree or still target `/chat/completions`.

- [ ] **Step 3: Add/update scripts and README**

Both scripts send one JSON request to `/api/v1/agentic-search`, print answer/session/reference summaries, log each request and response as JSONL, and redact the bearer token. README documents curl, PowerShell, Bash, and the future MCP input/output mapping.

- [ ] **Step 4: Run syntax and focused test checks**

Run:

```bash
pwsh -NoProfile -Command "[scriptblock]::Create((Get-Content scripts/test_agentic_search.ps1 -Raw)) | Out-Null"
bash -n scripts/test_agentic_search.sh
uv run pytest test/unit_test/test_agentic_search_scripts.py -q
```

Expected: all commands exit 0.

- [ ] **Step 5: Run the live 9380 smoke test**

Run the PowerShell script with the authorized local token, existing Chat Assistant, product dataset, registered model, and a query requiring citations. Expected response: `code=0`, non-empty answer, session ID, and at least one reference; the JSONL log must not contain the API key.

- [ ] **Step 6: Run final focused verification**

Run:

```bash
uv run pytest test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py test/unit_test/test_agentic_search_scripts.py -q
ruff check api/apps/services/agentic_search_api_service.py api/apps/restful_apis/agentic_search_api.py test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py test/unit_test/test_agentic_search_scripts.py
```

Expected: all tests pass and ruff reports no errors.

- [ ] **Step 7: Commit and push**

```bash
git add scripts/test_agentic_search.ps1 scripts/test_agentic_search.sh README.agentic-search.md test/unit_test/test_agentic_search_scripts.py
git commit -m "test: add agentic search smoke scripts"
git push origin chunk-mm
```
