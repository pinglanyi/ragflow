# Deployment retest: five compilation features

Initial deployed backend reported `95aa3de3b`. User then deployed `96e4ce228`, including the blank-input Wiki fix. Results below distinguish completed sample checks from pending product generation.

## Real product dataset

Dataset `982c06185fc011f1ae03d7c376fa307f`:

- Wiki task `3ae74f40c46e11f1a7fc079fc0a5151d`, started 13:48:33, completed with failure at 13:49:02: missing MAP extracts for **2** chunks, reduced from **3422** before pagination repair.
- Read-only comparison of current text/hash with historical MAP versions located exactly those two chunks: `11a35c3415006009` has empty text; `c03c15bb0313be35` contains only `" \n"`. The MAP batcher skips blank input, while the current-state scanner included it and required an impossible cache result.
- Follow-up fix: exclude blank source text from the current MAP baseline, without deleting or modifying source documents. Regression covers an entire first page of 1,000 blank chunks followed by a valid chunk. Test failed before the repair; 87 Wiki state/incremental tests pass afterward (rerun after deployment: 87 passed).
- After deploying `96e4ce228`, task `578ed89cc46f11f1bfba352a6845c70c` passed MAP for all 263 documents and entered entity matching at 13:57:18. At 14:06 the task remained at progress 0.65, with no new progress message. This is **not a completed product Wiki acceptance**.
- Graph, Mind map and Timeline retries correctly fail with actionable missing-document-compilation input errors; no fake successful empty build remains. These are **not accepted as usable on the product dataset** until matching document structure compilation is configured and performed.
- Product navigation API returns 17 top-level entries.

## Independent sample dataset

Dataset `25677b88c44911f1b62f0301fcd77cb5` on deployed workers:

| Feature | Retest |
| --- | --- |
| Wiki | Task `5b4ce60ac46e11f1a7fc079fc0a5151d` completed, incremental no-change path reports up to date. |
| Graph | Task `5ac26c50c46e11f1a7fc079fc0a5151d` completed; 3 visible entities, 2 relations. |
| Mind map | Task `5aed463cc46e11f1a7fc079fc0a5151d` completed; 19 entities, 24 relations. |
| Timeline | Task `5b1cb5d4c46e11f1a7fc079fc0a5151d` completed; 6 entities, 5 relations. |
| Tree preset | Builtin endpoint returns empty unused entity/relation collections, confirming the saveability fix was deployed. |
| PageIndex | Explicitly reparsed document `d3b09fbec46a11f1a2ee31197e3e063f`; task `673221cec46e11f1a7fc079fc0a5151d` received again at 13:56:46 after restart, remained RUNNING at progress 0.0196097 with no structure output. Existing results are not a substitute for this new parse. |

## Browser verification after restart

Using test2 on the diagnostic dataset, the compilation page loaded and switched among views without dynamic-module errors:

- Wiki: selected the Sampling concept and read generated body text, cross-links and source reference.
- Graph: 3 visible nodes and 2 connecting edges rendered.
- Mind map: central topic, branches and sensor specification leaves rendered.
- Timeline: installation, sampling verification and supply safety events rendered against October 1, 2 and 3 respectively. Labels wrap awkwardly in the current viewport; generation and rendering are functional.
- Tree/PageIndex: expanded the existing five-template sample document through document/title/section levels and opened `2 Sampling`, whose description displayed correctly. This verifies existing navigation output, not the pending fresh PageIndex generation.
- Captured browser error log after these checks was empty.

Screenshots saved in the task artifact directory: `deployed-wiki-page.png`, `deployed-graph.png`, `deployed-mindmap.png`, `deployed-timeline.png`, `deployed-pageindex-detail.png`.

## Runtime investigation

At 14:06, system status returned fresh heartbeats for worker 6/7/8 with 9/10/10 current tasks, respectively. Worker 6 still listed both acceptance tasks. User confirmed PID 225528 was alive with approximately 104% CPU and 5.3 GiB RSS. Multiple other PDF parsing tasks were in the same workers' current-task lists; resource contention is possible, but not proven as the cause.

The repeated `Conv ... running in Fallback mode` warning is emitted by ONNX Runtime's CUDA convolution implementation when selecting the cuDNN fallback heuristic. It does not itself mean CPU execution. Source: https://github.com/microsoft/onnxruntime/blob/main/onnxruntime/core/providers/cuda/nn/conv.cc . A process thread dump is requested to locate the actual wait/computation; no speculative runtime changes were applied.

User subsequently supplied a py-spy dump for PID 225528. MainThread was idle in the asyncio selector. One active thread was in ONNX OCR inference from table-orientation evaluation; two other threads were in multimodal chat calls (one DNS lookup, one SSL response read). This snapshot establishes concurrent OCR/model activity, but does not expose the suspended Wiki/PageIndex coroutine's await chain and therefore does not prove their specific blocking cause. Fresh generation remains unaccepted pending task completion or further coroutine-level diagnostics.

This report distinguishes functioning sample paths from unresolved product configuration and deployment acceptance. No product documents were reparsed or deleted.
