# Retrieval identity and pagination protocol

The MCP server exposes the same LangChain tool objects as the Python agent. The
RAGFlow Python `chunk-mm` service and the agent must be upgraded together.

## Identity

Single IDs are strings named `chunk_id`, `doc_id`, or `dataset_id`. Collections
are named `chunk_ids`, `doc_ids`, or `dataset_ids`. A document is a whole source
file; a Chunk is a passage from that file; a dataset is a knowledge base.

- `search(query, top_k=5, exclude_chunk_ids=None, dataset_selection_mode="all", dataset_names="")`
- `open(chunk_id, window=2)`
- `navigate(doc_id, start_offset, end_offset, direction, top_k=1)`
- `read(doc_id, start_offset=None, end_offset=None, top_k=20)`
- `grep(doc_id, pattern, mode="phrase", top_k=5, *, offset=0)`
- `find_source_files(keyword, mode, scan_meta, top_k, dataset_names, dataset_ids)` is unchanged.

The documented comma-separated string representation of `dataset_ids` is
unchanged. `exclude_ids` and the document parameter `source_id` have been
replaced by `exclude_chunk_ids` and `doc_id`. Update keyword callers and saved
tool schemas. Existing positional argument order and defaults remain unchanged;
grep adds the optional keyword-only offset.

Returned chunks contain `chunk_id`, `doc_id`, `dataset_id`, `content`, optional
score/offsets, the source name and compact navigation metadata. Raw upstream
`id`, `source_id`, `document_id`, and `metafield.doc_id` are adapted at response
boundaries; a Chunk ID is never used as a fallback document ID. Existing stored
source metadata is not migrated or overwritten by this protocol change.

## Search completeness

`total` counts unique normalized, nonexcluded results in the configured hybrid
retrieval candidate window, not all rows in the knowledge base. The same fixed
window is used regardless of exclusions and page size. Child-to-parent
normalization and duplicate elimination happen before counting. Disjoint
embedding-model groups are merged and ranked globally. `has_more` is true when
that result set contains more chunks than this response returns.

The candidate window is at least the configured knn_top_k and rerank candidate
count (default knn_top_k: 1024). Corpus or permission changes between calls are
not a snapshot transaction. Use the same query and explicit dataset range when
reading successive pages. Add returned chunk IDs to `exclude_chunk_ids`; do not
add document IDs. At most 10000 exclusion IDs are accepted per request.

## Grep pagination

`offset` is the number of **matching results** to skip, not a document ordinal,
character position or page number. Results preserve document order. `total` is
the full number of phrase/term matches before pagination. Return
`has_more = offset + len(chunks) < total`. Empty or past-the-end pages have
`has_more=false`; total remains the match count. Next offset is the previous
offset plus the number of returned chunks. Changing the document can change
positions, so keep the document unchanged while paging.

```json
{
  "chunks": [{
    "chunk_id": "chunk_088", "doc_id": "doc_456", "dataset_id": "dataset_1",
    "start_offset": 87, "end_offset": 87, "content": "A3-00: parameter description"
  }],
  "total": 37,
  "has_more": true
}
```

Example first page: `grep(doc_id="doc_456", pattern="A3", top_k=5, offset=0)`.
If five matches are returned, request `offset=5` next. Invalid negative/string
offsets are rejected by the backend. A truncated backend response that omits
`total` or `has_more` is surfaced by the agent as an upgrade/protocol error,
rather than inventing a complete page from `len(chunks)`.

## Workbench

The Workbench chunk-by-source-page service now returns `doc_id`, `dataset_id`,
and canonical IDs on every chunk. It returns all matches on that source page,
so `total` equals the matched chunk count and `has_more=false`. `total_chunks`
remains available. The existing RAGFlow SDK and multimodal upstream request
field `document_id` remains an internal wire detail; it is not globally renamed
in upstream APIs that are outside the Agentic Search protocol.
