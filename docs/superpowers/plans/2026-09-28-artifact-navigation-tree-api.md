# Artifact Navigation Tree API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the RAGFlow Artifacts navigation tree APIs so the existing UI can load and delete compiled dataset navigation nodes without returning HTTP 405.

**Architecture:** Add a small service layer over the compiled-document index, reusing `_compiled_index_or_none`, `KnowledgebaseService.accessible`, and `settings.docStoreConn`. Expose four async handlers beside the existing artifact and skill routes. Keep the compiler and frontend unchanged.

**Tech Stack:** Python 3, Quart route handlers, RAGFlow document-store abstraction, pytest.

## Global Constraints

- Work only on the `chunk-mm` branch.
- Port only the navigation-tree API behavior from upstream commit `3e4c6dfc0`; do not merge the full commit.
- Missing compiled indexes and failed navigation searches return an empty result instead of breaking the Artifacts page.
- Subtree deletion follows `parent_kwd` breadth-first with a maximum depth of 64.
- API responses use the existing `get_result` envelope.

---

### Task 1: Navigation-tree service operations

**Files:**
- Modify: `api/apps/services/dataset_api_service.py`
- Test: `test/testcases/test_web_api/test_dataset_management/test_dataset_sdk_routes_unit.py`

**Interfaces:**
- Consumes: `_compiled_index_or_none(tenant_id: str, kb_id: str)`, `KnowledgebaseService.accessible`, `settings.docStoreConn`.
- Produces: `list_nav_clusters(dataset_id, tenant_id, page=1, page_size=1000)`, `list_nav_children(dataset_id, tenant_id, name, page=1, page_size=1000)`, `delete_nav(dataset_id, tenant_id)`, and `delete_nav_node(dataset_id, tenant_id, name)` returning `(success: bool, result: dict | str)`.

- [ ] **Step 1: Write failing service tests**

Add tests that assert root and child filters, UI node shaping, empty-index behavior, authorization failure, whole-tree deletion, and recursive descendant deletion.

```python
success, result = _run(module.dataset_api_service.list_nav_clusters("kb-1", "tenant-1"))
assert success is True
assert result["items"][0]["type"] == "cluster"
assert search_calls[0]["condition"] == {
    "compile_kwd": ["dataset_nav"],
    "type_kwd": ["nav_cluster"],
    "parent_kwd": ["root"],
}
```

- [ ] **Step 2: Run tests and verify the missing functions fail**

Run:

```powershell
..\mistral-agentic-search-research\.venv\Scripts\python.exe -m pytest -c NUL --confcutdir=test/testcases/test_web_api/test_dataset_management test/testcases/test_web_api/test_dataset_management/test_dataset_sdk_routes_unit.py -k nav -q
```

Expected: FAIL because `list_nav_clusters`, `list_nav_children`, `delete_nav`, and `delete_nav_node` do not exist.

- [ ] **Step 3: Implement the service functions**

Add constants for `dataset_nav`, root parent, and selected fields; convert stored rows into `{name, description, doc_count, type, doc_id, has_children}`; query roots/children with paging; delete the full tree or a recursively discovered subtree.

- [ ] **Step 4: Run service tests**

Run the Step 2 command. Expected: all navigation service tests PASS.

### Task 2: REST routes and regression verification

**Files:**
- Modify: `api/apps/restful_apis/dataset_api.py`
- Test: `test/testcases/test_web_api/test_dataset_management/test_dataset_sdk_routes_unit.py`

**Interfaces:**
- Consumes: the four service functions from Task 1.
- Produces: `GET /datasets/<dataset_id>/nav`, `GET /datasets/<dataset_id>/nav/<path:name>/children`, `DELETE /datasets/<dataset_id>/nav`, and `DELETE /datasets/<dataset_id>/nav/<path:name>`.

- [ ] **Step 1: Write failing route tests**

Add handler tests that unwrap the authentication decorators, stub each service call, and verify success, authorization error, and internal-error response envelopes.

```python
res = _run(inspect.unwrap(module.list_dataset_nav)("tenant-1", "kb-1"))
assert res["code"] == module.RetCode.SUCCESS
assert res["data"] == {"total": 1, "items": [{"name": "产品"}]}
```

- [ ] **Step 2: Run route tests and verify missing handlers fail**

Run the Task 1 pytest command. Expected: FAIL because the four route handlers do not exist.

- [ ] **Step 3: Implement the four route handlers**

Each handler awaits its matching service function, returns `get_result(data=result)` on success, maps service authorization failures to `RetCode.AUTHENTICATION_ERROR`, and maps unexpected exceptions to `get_error_data_result(message="Internal server error")`.

- [ ] **Step 4: Run focused and full route tests**

Run:

```powershell
..\mistral-agentic-search-research\.venv\Scripts\python.exe -m pytest -c NUL --confcutdir=test/testcases/test_web_api/test_dataset_management test/testcases/test_web_api/test_dataset_management/test_dataset_sdk_routes_unit.py -q
```

Expected: PASS.

- [ ] **Step 5: Review, commit, and push**

```powershell
git diff --check
git status --short
git add api/apps/services/dataset_api_service.py api/apps/restful_apis/dataset_api.py test/testcases/test_web_api/test_dataset_management/test_dataset_sdk_routes_unit.py docs/superpowers/plans/2026-09-28-artifact-navigation-tree-api.md
git commit -m "fix: restore artifact navigation tree API"
git push origin HEAD:refs/heads/chunk-mm
```
