# Artifact Navigation Tree API Design

## Problem

The dataset compilation UI already loads the navigation tree through
`GET /api/v1/datasets/{dataset_id}/nav` and lazily loads children through
`GET /api/v1/datasets/{dataset_id}/nav/{name}/children`. The `chunk-mm`
backend does not register these routes or their service methods. The request
therefore reaches no GET handler and the UI reports `405 Method Not Allowed`.

## Scope

Restore only the navigation-tree HTTP contract and its dataset service logic.
Do not merge the complete upstream tree-navigation commit because it also
changes compilation runners, task execution, storage adapters, and database
models outside this defect.

## API Contract

The backend will provide four authenticated dataset routes:

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/api/v1/datasets/{dataset_id}/nav` | Return top-level navigation clusters. |
| `GET` | `/api/v1/datasets/{dataset_id}/nav/{name}/children` | Return the direct children of one node. |
| `DELETE` | `/api/v1/datasets/{dataset_id}/nav` | Delete the complete navigation tree. |
| `DELETE` | `/api/v1/datasets/{dataset_id}/nav/{name}` | Delete one node and all descendants. |

Successful list responses retain the frontend contract:

```json
{
  "code": 0,
  "data": {
    "total": 1,
    "items": [
      {
        "name": "模块",
        "description": "模块资料",
        "doc_count": 2,
        "type": "nav_cluster",
        "has_children": true
      }
    ]
  }
}
```

Delete responses return `{"deleted": <count>}` inside `data`.

## Service Design

The service will use the compiled-document index already written by
`rag/advanced_rag/knowlege_compile/dataset_nav.py`.

- Top-level nodes are rows with `compile_kwd=dataset_nav`,
  `type_kwd=nav_cluster`, and the root `parent_kwd` value.
- Child requests match `compile_kwd=dataset_nav` and the requested
  `parent_kwd`.
- Results are normalized to the existing TypeScript `DatasetNavList` shape.
- Node deletion walks descendants by `parent_kwd` with a bounded depth guard,
  then deletes the collected names in one dataset index.
- Whole-tree deletion removes all rows with the navigation compile marker.

Every service method first calls `KnowledgebaseService.accessible` and derives
the document-store index from the dataset owner. Missing indexes produce empty
lists or `deleted: 0` rather than server errors.

## Error Handling

- Missing permission returns the existing authentication error envelope.
- Empty node names return an empty child list or zero deletions.
- Document-store exceptions are logged server-side and returned through the
  existing safe API error messages.
- URL path names remain percent-encoded by the existing frontend client and
  are decoded by the Quart path converter.

## Verification

Add route-contract tests for all four methods and service tests covering:

- empty tree;
- top-level and child normalization;
- authorization rejection;
- complete-tree deletion;
- recursive node deletion;
- non-ASCII and slash-containing node names.

After deployment, open the dataset Artifacts Tree tab and verify the initial
GET returns HTTP 200 with an empty or populated `items` array instead of 405.
