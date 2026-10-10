# Deployment retest: five compilation features

Deployed backend reported `95aa3de3b`; includes the previous Wiki pagination, structure missing-input and Tree preset fixes.

## Real product dataset

Dataset `982c06185fc011f1ae03d7c376fa307f`:

- Wiki task `3ae74f40c46e11f1a7fc079fc0a5151d`, started 13:48:33, completed with failure at 13:49:02: missing MAP extracts for **2** chunks, reduced from **3422** before pagination repair.
- Read-only comparison of current text/hash with historical MAP versions located exactly those two chunks: `11a35c3415006009` has empty text; `c03c15bb0313be35` contains only `" \n"`. The MAP batcher skips blank input, while the current-state scanner included it and required an impossible cache result.
- Follow-up fix: exclude blank source text from the current MAP baseline, without deleting or modifying source documents. Regression covers an entire first page of 1,000 blank chunks followed by a valid chunk. Test failed before the repair; 87 Wiki state/incremental tests pass afterward. Requires deployment and another product Wiki run.
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
| PageIndex | Explicitly reparsed document `d3b09fbec46a11f1a2ee31197e3e063f`; final status still being checked. Existing results are not a substitute for this new parse. |

This report distinguishes functioning sample paths from unresolved product configuration and deployment acceptance. No product documents were reparsed or deleted.
