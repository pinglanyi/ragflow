# Five compilation features: live acceptance, 2026-10-10

Targets: Python API `10.37.0.21:9380`, UI `10.37.0.21:9222`.
Product dataset: `982c06185fc011f1ae03d7c376fa307f` (test1).
Isolated acceptance dataset: `25677b88c44911f1b62f0301fcd77cb5` (test2).

| Feature | Live acceptance sample | Product dataset / remaining work |
| --- | --- | --- |
| Wiki | 9 documents processed; task completed with +24 pages. Navigation renders. | Product task fails loading MAP cache beyond 10,000 records. Fixed historical and active-state pagination. Requires deployment and product task rerun. |
| Tree/PageIndex | PageIndex sample: 4 titles, 6 evidence claims, 9 relations. UI expands topic → document → title → Installation/Sampling/Maintenance; Sampling detail renders. Tree compiler also produced a summary node for the small sample. | Builtin Tree preset has invalid empty entity/relation type placeholders. Removed these unused items. Existing saved presets are not rewritten. Product Tree hierarchy was not rebuilt. |
| Graph | File compiler: 4 entities/4 relations. Dataset merge completed; UI shows 3 visible entities and 2 relations. | Product merge reports success with “No doc_graph rows found”; result is empty. Changed missing-input and wrong-template branches to fail with an instruction to attach a matching file compilation template and compile documents. Product requires document structure compilation before aggregation. |
| Mind map | File and dataset output: 19 entities/24 relations. UI renders the hierarchy and source facts. | Product has no aggregate result/task. Requires matching file compilation output before dataset aggregation. |
| Timeline | File and dataset output: 6 entities/5 relations. UI displays three dates and the corresponding installation, sampling and safety events. | Product has no aggregate result/task. Requires matching file compilation output before dataset aggregation. |

## Fix validation

- Wiki state and incremental unit regression: 86 passed, including 13,422-row cache/state cases which failed before the fix.
- Missing structure input, Tree preset and existing Wiki template inheritance: 10 passed. Missing-input cases and Tree preset test failed before their fixes.
- Read-only validation against the real product ES index, using the existing connector's search-after implementation and the new keyword sort tuple: expected 13,420 MAP versions, read 13,420 unique versions, zero duplicates.
- Browser console error log for the acceptance tab was empty after checking all five views.
- `git diff --check` passed.
- Full structure-merger tests could not collect in this local minimal runtime because `elastic_transport` is missing. Live compiler/merger acceptance above succeeded on the deployed runtime. Tests from different suites also use conflicting module stubs and were run separately.

## Scope and deployment

No existing product documents were reparsed or deleted. Live generation used a new synthetic document and file-template group in the isolated diagnostic dataset. The Tree sample used empty unused entity/relation collections, equivalent to the preset repair.

Deploy these changes and restart the Python backend and this stack's workers, then retry product Wiki. Graph/Mind map/Timeline need matching document compilation templates and their document-level results; clicking aggregate alone cannot create those inputs. Do not treat the isolated sample acceptance as acceptance of the full product dataset.

Evidence files are in the local acceptance artifact directory: `five-compilation-results.json`, `product-five-check.json`, `wiki-es-pagination-validation.json`, `pageindex-five-acceptance.png`.
