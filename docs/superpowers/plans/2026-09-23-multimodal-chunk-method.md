# Configurable Multimodal Chunk Method Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `/api/v1/multimodal/parse` and `/api/v1/multimodal/upload-and-parse` apply a caller-selected PDF chunk method while preserving safe image parsing and backward-compatible defaults.

**Architecture:** Extend the HTTP contract with an optional top-level `chunk_method`. Resolve and validate it once in the submission service, persist the effective value in the durable multimodal job config, and reuse it for initial dispatch and recovered tasks. PDF requests may select a supported document parser; static images remain `picture`.

**Tech Stack:** Python, Quart, Peewee, pytest/unittest, RAGFlow task services.

## Global Constraints

- Work on the existing `chunk-mm` branch.
- Existing requests without `chunk_method` remain PDF=`naive`, image=`picture`.
- Static images reject any chunk method other than `picture` before task creation.
- Do not expose provider credentials or internal exception text in API responses.
- Initial dispatch and task recovery must use the same persisted parser ID.

---

### Task 1: Extend the multimodal HTTP contract

**Files:**
- Modify: `api/apps/restful_apis/multimodal_api.py`
- Test: `test/unit_test/test_multimodal_api.py`

**Interfaces:**
- Produces: `service.submit(tenant_id, dataset_id, document_id, options, chunk_method)`
- Produces: `service.upload(tenant_id, dataset_id, file, options, chunk_method)`

- [ ] **Step 1: Write failing route contract tests**

Add tests proving JSON and multipart requests accept and forward the field:

```python
async def test_parse_forwards_chunk_method(self):
    res = await self.client.post(
        "/api/v1/multimodal/parse",
        headers=self.headers,
        json={"dataset_id": "kb", "document_id": "doc", "chunk_method": "paper"},
    )
    self.assertEqual(res.status_code, 202)
    self.assertEqual(self.calls[0][1][-1], "paper")

async def test_upload_forwards_chunk_method(self):
    res = await self.client.post(
        "/api/v1/multimodal/upload-and-parse",
        headers=self.headers,
        form={"dataset_id": "kb", "multimodal": '{"model":"m"}', "chunk_method": "picture"},
        files={"file": FileStorage(io.BytesIO(b"fake png"), filename="x.png")},
    )
    self.assertEqual(res.status_code, 202)
    self.assertEqual(self.calls[0][1][-1], "picture")
```

- [ ] **Step 2: Run tests and confirm the new field is rejected**

Run: `python -m pytest test/unit_test/test_multimodal_api.py -q`

Expected: the new tests fail because `chunk_method` is not in the accepted field sets.

- [ ] **Step 3: Forward the optional field**

Update the route bodies:

```python
allowed = {"dataset_id", "document_id", "multimodal", "chunk_method"}
if not isinstance(body, dict) or set(body) - allowed:
    raise service.ApiError("Expected dataset_id, document_id, optional multimodal object and optional chunk_method")
chunk_method = body.get("chunk_method")
if chunk_method is not None and (not isinstance(chunk_method, str) or not chunk_method.strip()):
    raise service.ApiError("chunk_method must be a non-empty string")
data = await thread_pool_exec(
    service.submit, tenant_id, dataset_id, document_id, options,
    chunk_method.strip() if chunk_method else None,
)
```

For multipart, add `chunk_method` to allowed form fields and pass the stripped value to `service.upload`.

- [ ] **Step 4: Run route tests**

Run: `python -m pytest test/unit_test/test_multimodal_api.py -q`

Expected: all route contract tests pass.

- [ ] **Step 5: Commit the HTTP contract**

```bash
git add api/apps/restful_apis/multimodal_api.py test/unit_test/test_multimodal_api.py
git commit -m "feat(multimodal): accept chunk method override"
```

### Task 2: Resolve, validate, and persist the effective parser

**Files:**
- Modify: `api/apps/services/multimodal_api_service.py`
- Modify: `api/db/services/multimodal_job_service.py`
- Test: `test/unit_test/test_multimodal_jobs.py`

**Interfaces:**
- Produces: `resolve_chunk_method(filename: str, requested: str | None) -> str`
- Persists: `job.config["multimodal_chunk_method"]`

- [ ] **Step 1: Write failing service tests**

Add tests for defaults, PDF override, image rejection, and durable storage:

```python
def test_pdf_chunk_override_is_persisted_and_dispatched(self):
    service, doc = self.submission_service()
    service.submit("tenant", "kb", "doc", {}, "paper")
    self.assertEqual(self.Job.get().config["multimodal_chunk_method"], "paper")
    update = service.DocumentService.update_by_id.call_args.args[1]
    self.assertEqual(update["parser_id"], "paper")

def test_image_rejects_non_picture_chunk(self):
    service, doc = self.submission_service()
    doc.name = "x.png"
    with self.assertRaises(service.ApiError) as error:
        service.submit("tenant", "kb", "doc", {}, "manual")
    self.assertEqual(error.exception.status, 400)
    self.assertEqual(self.Job.select().count(), 0)
```

Also assert omitted values still resolve to `naive` for PDF and `picture` for images.

- [ ] **Step 2: Run focused tests and confirm hard-coded behavior fails them**

Run: `python -m pytest test/unit_test/test_multimodal_jobs.py -q`

Expected: override and rejection tests fail because the service currently selects by suffix only.

- [ ] **Step 3: Implement one resolver**

Add a resolver used before job creation:

```python
PDF_CHUNK_METHODS = {
    "naive", "manual", "paper", "book", "laws", "presentation",
    "qa", "table", "one", "tag", "resume",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

def resolve_chunk_method(filename, requested=None):
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        if requested not in (None, "picture"):
            raise ApiError("Static images require chunk_method=picture")
        return "picture"
    effective = requested or "naive"
    if suffix != ".pdf" or effective not in PDF_CHUNK_METHODS:
        raise ApiError(f"Unsupported multimodal chunk_method for {suffix or 'file'}: {effective}")
    return effective
```

Change `submit(..., options, chunk_method=None)` to resolve before `Jobs.create`, copy the value into `config["multimodal_chunk_method"]`, and use it for `DocumentService.update_by_id` and `task_doc["parser_id"]`. Change `upload(..., options, chunk_method=None)` to pass the field into `submit`.

- [ ] **Step 4: Preserve the parser during task recovery**

Replace the suffix-only assignment in `MultimodalJobService.prepare_task`:

```python
task["parser_id"] = job.config.get("multimodal_chunk_method") or (
    "naive" if task.get("type") == "pdf" else "picture"
)
```

- [ ] **Step 5: Run multimodal service tests**

Run: `python -m pytest test/unit_test/test_multimodal_jobs.py test/unit_test/test_multimodal_api.py -q`

Expected: all tests pass, including legacy defaults and recovered-task parser assertions.

- [ ] **Step 6: Commit durable parser selection**

```bash
git add api/apps/services/multimodal_api_service.py api/db/services/multimodal_job_service.py test/unit_test/test_multimodal_jobs.py
git commit -m "feat(multimodal): persist selected chunk method"
```

### Task 3: Document and verify the RAGFlow change

**Files:**
- Modify: `docs/chunk-multimodal-api.md`

**Interfaces:**
- Documents request field `chunk_method` and compatibility rules.

- [ ] **Step 1: Update the API example**

Document this payload and state that omission preserves legacy defaults:

```json
{
  "dataset_id": "dataset-id",
  "document_id": "document-id",
  "chunk_method": "paper",
  "multimodal": {"model": "qwen-vl", "max_tokens": 8192}
}
```

- [ ] **Step 2: Run syntax and focused unit verification**

Run: `python -m compileall api/apps/restful_apis/multimodal_api.py api/apps/services/multimodal_api_service.py api/db/services/multimodal_job_service.py`

Run: `python -m pytest test/unit_test/test_multimodal_api.py test/unit_test/test_multimodal_jobs.py -q`

Expected: compilation succeeds and all focused tests pass.

- [ ] **Step 3: Run the repository-required multimodal suite**

Run: `python -m pytest test/unit_test/test_chunk_multimodal_archive.py test/unit_test/test_multimodal_api.py test/unit_test/test_multimodal_jobs.py -q`

Expected: all tests pass.

- [ ] **Step 4: Commit documentation**

```bash
git add docs/chunk-multimodal-api.md
git commit -m "docs(multimodal): describe chunk method selection"
```
