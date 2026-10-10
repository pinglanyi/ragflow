# Existing chunks: compile and aggregate

The compilation page now has a Python-only **Compile existing chunks** action.
It calls `POST /api/v1/datasets/{id}/compile-existing` and queues one existing
`structure` task in the configured task queue. Graph, Mind map and Timeline
share its task ID and progress. Existing indexing endpoints retain their behavior.

The worker reads available source chunks without `compile_kwd`, skips blank
documents, and refuses sources still being parsed. It uses document/dataset
template groups first. Missing kinds use tenant-owned editable copies of the
built-in templates. The operation disables rechunking, synthesis and per-document
dataset merging without changing saved template or parser settings.

One document is prepared at a time; its chunk snapshot is shared by the three
templates. The LLM pool has a hard ceiling of three calls. Content, effective
template settings and model configuration determine checkpoints in Redis (30-day
TTL). Retries reuse successful unchanged documents, and rebuild changed/failed
documents. Missing nonempty outputs invalidate reuse. Failed source reads,
model calls and writes prevent completion and dataset aggregation. The dataset
lock renews while the operation runs.

The final aggregation runs once per template, using a full rebuild to remove
stale entities after edits. No source chunks are deleted, rewritten or sent to
OCR. This is not a transaction across all three derived dataset outputs: an
aggregation error can leave some updated structures; retry reuses completed
document compilation and retries aggregation.

Validation:

- Seven new backend regressions: reuse, changed content/settings/model identity,
  cancellation, raw chunk preservation, failed-document retry, queue opt-in,
  disabled-document exclusion and shared progress IDs.
- Six existing missing-structure-input regressions pass.
- Four strict-store regressions verify errors propagate in the new operation
  while the existing best-effort entry points retain their policy.
- 87 existing Wiki MAP/incremental regressions pass when run with their shared
  fixture setup. Combining unrelated test-directory import stubs is unsupported.
- Three frontend interaction tests pass: start and refresh all three views,
  prevent duplicate clicks, surface business errors.
- Changed frontend files pass targeted lint; Python syntax compilation passes.
- Production frontend build passes (Vite, 5m 15s; existing chunk-size warnings).
- Full TypeScript check still reports repository baseline errors (including
  `getMetaKeys` referenced in HEAD's service but absent from HEAD's API map).
  No diagnostic names the new button or compilation page.

Deployment acceptance remains necessary: restart this stack's backend and
workers, refresh the frontend, run the new action on a small parsed dataset,
inspect all three structures, then retry and verify reused counts. Compare source
chunk IDs/content before and after, then run against the product dataset. Wiki
and PageIndex keep their separate existing entry points.
