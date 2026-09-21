# Agentic Search Dataset Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route stateless Agentic Search requests to one to three relevant, authorized RAGFlow knowledge bases when callers omit `dataset_ids`, while accepting a single comma-separated manual override.

**Architecture:** Keep request parsing, catalog loading, LLM routing, selection validation, and Agentic Search execution as distinct functions in the existing API service. Resolve the effective chat model before routing, let the model select from sanitized knowledge-base metadata, then validate authorization and embedding compatibility in application code before calling the existing `rag_agent` path.

**Tech Stack:** Python 3.13, Quart, Peewee service layer, RAGFlow `LLMBundle`, `rag.prompts.generator.gen_json`, pytest, PowerShell, Bash/curl/jq.

**Spec:** `docs/superpowers/specs/2026-09-21-agentic-search-dataset-routing-design.md`

## Global Constraints

- `dataset_ids` is one optional comma-separated string; JSON arrays are rejected.
- Omitting `dataset_ids` in stateless mode activates automatic dataset routing.
- Automatic routing considers only knowledge bases visible to the authenticated user, valid in RAGFlow, and containing at least one parsed chunk.
- The router selects one to three datasets from one embedding-compatible group.
- Knowledge-base descriptions are untrusted routing metadata and never become answer evidence or citations.
- Invalid or empty router output fails closed and never falls back to searching every dataset.
- Existing `chat_id` and `session_id` behavior remains functional.
- Provider credentials and complete descriptions are excluded from server logs.

## Review Focus

- A `dataset_ids` value containing only commas and whitespace must fail validation instead of activating automatic routing.
- Model output containing an unauthorized dataset ID must fail closed, even if another returned ID is authorized.
- Model output selecting datasets from different embedding model groups must fail before retrieval.
- A joined-tenant catalog must preserve RAGFlow's permission filtering and exclude zero-chunk knowledge bases.
- A stateful request without a manual override must use and report the chat's validated dataset scope without invoking automatic routing.

---

### Task 1: Comma-separated request contract

**Files:**
- Modify: `api/apps/services/agentic_search_api_service.py`
- Modify: `test/unit_test/api/apps/services/test_agentic_search_api_service.py`
- Modify: `test/testcases/restful_api/test_agentic_search_routes_unit.py`

**Interfaces:**
- Produces: `parse_dataset_ids(value: str) -> list[str]`.
- Changes: `validate_agentic_search_request(payload: dict) -> dict` accepts omitted `dataset_ids` and normalizes a supplied comma-separated string into an internal `list[str]`.
- Preserves: `session_id` remains invalid without `chat_id`.

- [ ] **Step 1: Write failing request validation tests**

Replace list-based fixtures and add these assertions:

```python
def test_validate_accepts_stateless_auto_routing():
    result = validate_agentic_search_request({"query": "hello"})
    assert result["query"] == "hello"
    assert "dataset_ids" not in result


def test_validate_normalizes_comma_separated_dataset_ids():
    result = validate_agentic_search_request(
        {"query": "hello", "dataset_ids": " kb-1, kb-1, ,kb-2 "}
    )
    assert result["dataset_ids"] == ["kb-1", "kb-2"]


@pytest.mark.parametrize("value", [["kb-1"], 3, None, " , , "])
def test_validate_rejects_invalid_explicit_dataset_ids(value):
    payload = {"query": "hello", "dataset_ids": value}
    with pytest.raises(ValueError, match="dataset_ids"):
        validate_agentic_search_request(payload)
```

Use a sentinel in the last test so omitted `dataset_ids` remains distinct from explicit JSON `null`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
D:/Anaconda/envs/fcd/python.exe -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py -q
```

Expected: failures show that the current validator requires a list and rejects a stateless request without a scope.

- [ ] **Step 3: Implement the minimal request parser**

Add a private missing-value sentinel and implement:

```python
def parse_dataset_ids(value: str) -> list[str]:
    if not isinstance(value, str):
        raise ValueError("dataset_ids must be a comma-separated string")
    dataset_ids = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not dataset_ids:
        raise ValueError("dataset_ids must contain at least one dataset ID")
    return dataset_ids
```

Only call it when the field is present. Remove the validation rule requiring either `chat_id` or `dataset_ids`; retain the rule rejecting `session_id` without `chat_id`.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 1 command and expect all tests to pass.

- [ ] **Step 5: Commit the request contract**

```bash
git add api/apps/services/agentic_search_api_service.py test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py
git commit -m "feat: accept automatic agentic dataset scope"
```

### Task 2: Authorized dataset router

**Files:**
- Modify: `api/apps/services/agentic_search_api_service.py`
- Modify: `test/unit_test/api/apps/services/test_agentic_search_api_service.py`

**Interfaces:**
- Produces: `load_routable_datasets(*, user_id: str) -> list[dict]`.
- Produces: `build_dataset_router_prompt(*, query: str, datasets: list[dict]) -> tuple[str, str]`.
- Produces: `validate_dataset_selection(selection: object, datasets: list[dict]) -> list[dict]`.
- Produces: `select_datasets(*, tenant_id: str, query: str, datasets: list[dict], model_config: dict) -> list[dict]`.
- Selection items have `id: str`, `name: str`, `reason: str`, and `confidence: float`.

- [ ] **Step 1: Write failing catalog and selection tests**

Add focused tests that pin the boundaries:

```python
def test_filter_routable_datasets_excludes_empty_knowledge_bases():
    rows = [
        {"id": "empty", "name": "Empty", "description": "", "chunk_num": 0, "embd_id": "e1"},
        {"id": "ready", "name": "Ready", "description": "manual", "chunk_num": 2, "embd_id": "e1"},
    ]
    assert MODULE.filter_routable_datasets(rows) == [
        {"id": "ready", "name": "Ready", "description": "manual", "embd_id": "e1"}
    ]


def test_validate_dataset_selection_rejects_unknown_ids():
    catalog = [{"id": "kb-1", "name": "Manual", "description": "", "embd_id": "embed-a"}]
    with pytest.raises(ValueError, match="unauthorized"):
        MODULE.validate_dataset_selection(
            {"selected": [{"id": "kb-1", "confidence": 0.9}, {"id": "foreign", "confidence": 0.8}]},
            catalog,
        )


def test_validate_dataset_selection_limits_count_and_embedding_group():
    catalog = [
        {"id": "a", "name": "A", "description": "", "embd_id": "embed-a@x"},
        {"id": "b", "name": "B", "description": "", "embd_id": "embed-b@y"},
    ]
    with pytest.raises(ValueError, match="embedding"):
        MODULE.validate_dataset_selection(
            {"selected": [{"id": "a", "confidence": 2}, {"id": "b", "confidence": -1}]},
            catalog,
        )
```

Also assert that the prompt contains the question and JSON-serialized candidate metadata, labels descriptions as untrusted data, groups candidates by base embedding model, and contains no credentials.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
D:/Anaconda/envs/fcd/python.exe -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py -q
```

Expected: failures because catalog filtering, prompt construction, and validated routing functions do not exist.

- [ ] **Step 3: Implement catalog loading and validated model selection**

Use the existing services and model utilities:

```python
joined = await thread_pool_exec(TenantService.get_joined_tenants_by_user_id, user_id)
joined_ids = [row["tenant_id"] for row in joined]
rows, _ = await thread_pool_exec(
    KnowledgebaseService.get_by_tenant_ids,
    joined_ids,
    user_id,
    0,
    0,
    "update_time",
    True,
    "",
)
```

Filter to `chunk_num > 0`, serialize only `id`, `name`, `description`, and `embd_id`, and raise `ValueError("No accessible parsed datasets are available")` when empty. Build `LLMBundle(tenant_id, model_config)` and call:

```python
selection = await gen_json(system_prompt, user_prompt, chat_mdl, gen_conf={"temperature": 0.0})
```

Validate the response is a dictionary with a nonempty `selected` list of at most three items. Reject every unknown ID, deduplicate IDs, normalize `reason` to a stripped string, clamp numeric confidence into `0.0..1.0`, and run `validate_dataset_embedding_models` on the selected knowledge-base objects before retrieval. Do not fall back to all datasets.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Task 2 command and expect all tests to pass.

- [ ] **Step 5: Commit the router**

```bash
git add api/apps/services/agentic_search_api_service.py test/unit_test/api/apps/services/test_agentic_search_api_service.py
git commit -m "feat: route agentic search by dataset description"
```

### Task 3: Integrate routing into Agentic Search execution

**Files:**
- Modify: `api/apps/services/agentic_search_api_service.py`
- Modify: `test/unit_test/api/apps/services/test_agentic_search_api_service.py`

**Interfaces:**
- Changes: `execute_agentic_search(...)` resolves the effective model before automatic routing and sends the selected IDs to `rag_agent`.
- Changes: `normalize_agentic_search_result(...)` accepts `dataset_selection_mode: str` and `selected_datasets: list[dict]`.
- Response adds `dataset_selection_mode` and `selected_datasets`.

- [ ] **Step 1: Write failing execution-path tests**

Add `test_execute_stateless_search_routes_when_dataset_ids_are_omitted`. Its
catalog contains `kb-1` and `kb-2`, the router selects `kb-2`, and `rag_agent`
captures the dialog. Assert `dialog.kb_ids == ["kb-2"]`, the response mode is
`auto`, the selected trace contains `kb-2`, and the Dialog and Conversation
save/update stubs have zero calls.

Add `test_execute_manual_scope_bypasses_router`. Pass internal
`dataset_ids=["kb-1"]`, install a `gen_json` stub that raises on every call,
and assert the response mode is `manual` with one selected trace for `kb-1`.

Add `test_execute_chat_scope_reports_validated_chat_datasets`. Supply a
`chat_id` and `session_id`, omit `dataset_ids`, install the same raising router
stub, and assert the response mode is `chat`, `rag_agent` receives the stored
chat scope, and every stored ID is authorized before retrieval.

Add separate tests whose router result contains an unknown ID and mixed
embedding IDs. Each test sets `rag_agent` to raise if called and asserts the
expected `ValueError` is raised first.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
D:/Anaconda/envs/fcd/python.exe -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py -q
```

Expected: automatic stateless execution fails because `dataset_ids` is absent, and normalized responses lack routing fields.

- [ ] **Step 3: Implement the selection branches**

Refactor execution in a fixed order. First load the requested chat, then resolve
the effective chat model and its configuration. When `dataset_ids` exists in
`options`, call `validate_explicit_dataset_scope` with that list and set mode to
`manual`. For a stateless request without the field, call
`load_routable_datasets(user_id=tenant_id)`, then `select_datasets` with the
query, catalog, tenant, and model configuration, and set mode to `auto`. For a
stateful request without the field, call `validate_explicit_dataset_scope` with
`source_dialog.kb_ids` and set mode to `chat`.

Build or copy the dialog with the selected IDs, log only request ID, mode, IDs, router duration, total duration, and reference count, then include selection metadata in the normalized response.

- [ ] **Step 4: Run service and route tests and verify GREEN**

Run:

```bash
D:/Anaconda/envs/fcd/python.exe -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py -q
```

Expected: all service and route tests pass.

- [ ] **Step 5: Commit execution integration**

```bash
git add api/apps/services/agentic_search_api_service.py test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py
git commit -m "feat: execute agentic search with automatic dataset routing"
```

### Task 4: One-click scripts and usage documentation

**Files:**
- Modify: `scripts/test_agentic_search.ps1`
- Modify: `scripts/test_agentic_search.sh`
- Modify: `test/unit_test/test_agentic_search_scripts.py`
- Modify: `README.agentic-search.md`

**Interfaces:**
- PowerShell consumes optional `[string]$DatasetIds = ""`.
- Bash consumes optional single `--dataset-id 'id1,id2'`.
- Both omit `dataset_ids` when empty so automatic routing is the default.

- [ ] **Step 1: Write failing script contract tests**

Replace repeated-list expectations with:

```python
def test_scripts_use_one_optional_comma_separated_dataset_argument():
    powershell = (ROOT / "scripts" / "test_agentic_search.ps1").read_text(encoding="utf-8")
    bash = (ROOT / "scripts" / "test_agentic_search.sh").read_text(encoding="utf-8")
    assert '[string]$DatasetIds = ""' in powershell
    assert "if ($DatasetIds) { $body.dataset_ids = $DatasetIds }" in powershell
    assert 'DATASET_IDS=""' in bash
    assert 'DATASET_IDS="$2"' in bash
    assert "dataset_ids:$datasets" in bash
    assert "DATASET_IDS+=(" not in bash


def test_scripts_allow_auto_routing_without_chat_or_dataset():
    powershell = (ROOT / "scripts" / "test_agentic_search.ps1").read_text(encoding="utf-8")
    bash = (ROOT / "scripts" / "test_agentic_search.sh").read_text(encoding="utf-8")
    assert "At least one DatasetIds" not in powershell
    assert "At least one --dataset-id" not in bash
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
D:/Anaconda/envs/fcd/python.exe -m pytest --noconftest test/unit_test/test_agentic_search_scripts.py -q
```

Expected: failures because both scripts currently require dataset IDs for stateless mode and serialize arrays.

- [ ] **Step 3: Update scripts and README**

Make automatic routing the first example in `README.agentic-search.md`. Document the single comma-separated override, `auto`/`manual`/`chat` response modes, selected dataset trace, authorization boundary, same-embedding requirement, router failure behavior, server logs, DeepAgent request mapping, and MCP input/output schema. Update curl, Python, PowerShell, and Bash examples to send a JSON string when overriding datasets.

- [ ] **Step 4: Run the focused and syntax checks**

Run:

```bash
D:/Anaconda/envs/fcd/python.exe -m pytest --noconftest test/unit_test/api/apps/services/test_agentic_search_api_service.py test/testcases/restful_api/test_agentic_search_routes_unit.py test/unit_test/test_agentic_search_scripts.py test/agentic_search -q
D:/Anaconda/envs/fcd/python.exe -m py_compile api/apps/restful_apis/agentic_search_api.py api/apps/services/agentic_search_api_service.py
bash -n scripts/test_agentic_search.sh
git diff --check
```

Parse PowerShell without executing it:

```powershell
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path 'scripts/test_agentic_search.ps1'),
  [ref]$null,
  [ref]$errors
) | Out-Null
if ($errors.Count) { $errors | Format-List | Out-String; exit 1 }
```

Expected: all targeted tests, compilation, script parsing, and whitespace checks pass.

- [ ] **Step 5: Commit documentation and scripts**

```bash
git add README.agentic-search.md scripts/test_agentic_search.ps1 scripts/test_agentic_search.sh test/unit_test/test_agentic_search_scripts.py
git commit -m "docs: explain automatic agentic dataset routing"
```

### Task 5: Review, runtime smoke test, and push

**Files:**
- Review: all changes since `13dd72f6f`
- Runtime: deployed RAGFlow API at `http://127.0.0.1:9380`

**Interfaces:**
- Consumes: a RAGFlow API key supplied through process arguments or environment variables.
- Produces: JSONL request/response logs outside version control.

- [ ] **Step 1: Review the completed diff**

Inspect:

```bash
git diff 13dd72f6f..HEAD --check
git diff 13dd72f6f..HEAD --stat
git status --short
```

Review authorization, prompt-injection boundaries, model-resolution order, selection validation, logging redaction, API examples, and test coverage. Fix any concrete issue and rerun the owning focused tests.

- [ ] **Step 2: Run the automatic routing smoke test**

Use the Bash or PowerShell script with the API key passed at runtime, a product-knowledge question, no `chat_id`, and no `dataset_ids`. Confirm HTTP success, `dataset_selection_mode: "auto"`, one to three selected datasets, a nonempty answer, and citations backed by returned chunks.

- [ ] **Step 3: Run the manual override smoke test**

Take two compatible IDs from the auto-routing result/catalog and call the script with one comma-separated argument. Confirm `dataset_selection_mode: "manual"`, the reported selected IDs match the override, and the call does not create a chat session.

- [ ] **Step 4: Re-run final verification after smoke findings**

Run every Task 4 verification command again. Record any unavailable external dependency or deployment mismatch by exact command and response; do not report it as a passing test.

- [ ] **Step 5: Push `chunk-mm` using the authorized SSH configuration**

```bash
git -c "core.sshCommand='C:/Program Files/Git/usr/bin/ssh.exe' -F 'D:/OneDrive - 宁波数字孪生(东方理工)研究院/IDT/项目/知识库相关/ssh/codex_ssh_config_utf8'" push ssh://git@ssh.github.com:443/pinglanyi/ragflow.git chunk-mm:chunk-mm
```

Confirm the remote branch points to the final local commit before reporting completion.
