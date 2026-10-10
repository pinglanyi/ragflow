# Executor queue isolation — 2026-10-10

## Behavior

`start.sh` exports `RAGFLOW_TASK_QUEUE_NAMESPACE=ragflow_python_${BACKEND_PORT}` by default. With backend port 9380, API producers and task executors use `te.ragflow_python_9380.1.common` and `te.ragflow_python_9380.0.common`. Both share the routing implementation in `common/task_queue.py`.

Launches without this environment variable retain the existing `te.1.common` and `te.0.common` streams. The default executor IDs remain 6, 7 and 8. Existing workers 3, 4 and 5 are neither stopped nor reconfigured. No Redis queues are deleted, flushed or migrated.

Worker heartbeat reports `task_queues`. The checker distinguishes competing workers, workers on other queues and older workers whose queues cannot be verified. It also checks expected worker IDs for mismatched, missing or stale queue reports. It does not infer GPU use from worker names or queue membership.

## Deployment

The backend and this project's workers must restart together on the first deployment. Starting workers alone leaves the running backend publishing to its previous queue.

```bash
git pull origin chunk-mm
TASK_EXECUTOR_OFFSET=6 RAGFLOW_TASK_QUEUE_NAMESPACE=ragflow_python_9380 bash start.sh restart
TASK_EXECUTOR_OFFSET=6 RAGFLOW_TASK_QUEUE_NAMESPACE=ragflow_python_9380 bash start.sh check-executors
```

Use a different namespace for each independent stack. Old pending tasks stay in their old queue; resubmit this project's unfinished test documents after switching if needed. Do not bulk move the shared queue because it contains other users' tasks.

## Verification

- 34 targeted unittest cases passed: queue naming, shell launch/stop scoping, heartbeat diagnostics and runtime bootstrap behavior.
- 20 existing queue settings cases passed against the actual extracted settings functions, with database/model imports isolated.
- Local tests do not validate CUDA: the real Torch/ORT bootstrap integration case was excluded because this Windows test runtime lacks the server's GPU environment.
- Independent review found that expected worker IDs could bypass queue validation. Added a regression covering old queues and missing queue reports, then fixed the diagnostic.

## Live OCR observation before deployment

An isolated diagnostic dataset was created through the API, using a four-page raster PDF and explicit DeepDOC parsing. Document `25b82a88c44911f1b62f0301fcd77cb5` in dataset `25677b88c44911f1b62f0301fcd77cb5` reached DONE with four chunks and 1298 tokens. The reported OCR stage took 2.59 seconds; total task time was 8.79 seconds. Worker 6's completed counter increased from zero to one.

This confirms successful OCR execution before the isolation change, but the deployed API did not report actual ONNX providers or GPU memory. CUDA execution remains unverified. The new queue isolation also requires deployment before a live isolation claim can be made.
