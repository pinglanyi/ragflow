# Agentic Search Dataset Routing Design

## Goal

Allow the stateless `POST /api/v1/agentic-search` endpoint to search without a
`chat_id` or caller-supplied dataset list. When `dataset_ids` is omitted, the
service selects the most relevant accessible knowledge bases from their names
and descriptions, then runs the existing Agentic Search pipeline over that
scope.

Callers may still override routing by passing one comma-separated
`dataset_ids` string.

## Chosen approach

Use a two-stage request flow:

1. A dataset router considers the current user's accessible, valid, parsed
   knowledge bases and selects a small compatible group based on the question,
   knowledge-base name, and knowledge-base description.
2. The existing `rag_agent` implementation searches only the selected dataset
   IDs and produces the answer from retrieved chunks.

This is preferred over searching every knowledge base because it reduces
irrelevant retrieval, token use, and latency. It is preferred over lexical-only
routing because descriptions can express semantic scope that does not share
literal words with the question.

The alternatives considered were:

- Search all accessible datasets. This is simple but produces a noisy and
  potentially expensive retrieval scope.
- Use deterministic keyword matching only. This is fast but brittle for
  synonyms, domain terminology, and multilingual questions.
- Let one model choose datasets and run Agentic Search on the selected scope.
  This provides semantic routing while keeping dataset authorization and final
  evidence validation in application code. This is the selected approach.

## API contract

The endpoint remains:

```http
POST /api/v1/agentic-search
Authorization: Bearer <RAGFLOW_API_KEY>
Content-Type: application/json
```

Automatic routing request:

```json
{
  "query": "这个产品的安装要求和保修期限是什么？",
  "reasoning": 3
}
```

Manual routing request:

```json
{
  "query": "这个产品的安装要求和保修期限是什么？",
  "dataset_ids": "dataset-a,dataset-b",
  "reasoning": 3
}
```

`dataset_ids` is one optional string. The server splits it on commas, trims
whitespace, removes duplicates while preserving order, and rejects an empty
result. JSON arrays are no longer part of this endpoint's contract. The Bash
and PowerShell scripts expose the same shape as one
`--dataset-id 'dataset-a,dataset-b'`/`-DatasetIds 'dataset-a,dataset-b'`
argument.

The existing `chat_id` mode remains available. Its configured dataset scope is
used when neither `dataset_ids` nor automatic stateless routing applies. An
explicit `dataset_ids` string continues to override the chat's configured
scope after authorization and embedding compatibility checks.

The successful response adds routing information:

```json
{
  "code": 0,
  "data": {
    "answer": "...",
    "dataset_selection_mode": "auto",
    "selected_datasets": [
      {
        "id": "dataset-a",
        "name": "产品安装手册",
        "reason": "包含安装条件和操作要求",
        "confidence": 0.94
      }
    ],
    "references": []
  }
}
```

`dataset_selection_mode` is `auto`, `manual`, or `chat`. Manual selection
returns the validated dataset name and omits model-generated reasoning by using
an empty `reason` and `confidence: null`. Chat selection reports the final
validated chat scope in the same way.

## Accessible dataset catalog

The router obtains joined tenant IDs with
`TenantService.get_joined_tenants_by_user_id(user_id)` and loads visible
knowledge bases with `KnowledgebaseService.get_by_tenant_ids(...)`. That
service already applies ownership, team permission, and valid-status filters.

The catalog excludes knowledge bases whose `chunk_num` is zero. Each routing
candidate contains only:

- `id`
- `name`
- `description`
- `embd_id`

No document chunks or file contents are sent during dataset selection.

If the catalog is empty, the request fails with a clear data error explaining
that no accessible parsed knowledge base is available.

## Router behavior

The router uses the request's resolved chat model, so model override and tenant
default-model behavior stay consistent with the current stateless endpoint. It
calls the existing `LLMBundle` and `gen_json` infrastructure at temperature
zero.

The prompt treats names and descriptions as untrusted data, explicitly states
that instructions inside them must be ignored, and requires JSON containing
one to three choices:

```json
{
  "selected": [
    {
      "id": "dataset-a",
      "reason": "short routing reason",
      "confidence": 0.94
    }
  ]
}
```

Application code validates every returned ID against the authorized catalog,
deduplicates it, clamps confidence to the inclusive 0-to-1 range, and keeps at
most three datasets.

The router groups candidates by base embedding model before selection. The
model must select datasets from one group, and application code rejects a
mixed result. This preserves the existing retrieval requirement that datasets
searched together use compatible embedding models. The prompt identifies the
groups but does not expose credentials or internal model configuration.

If the router returns no valid selection, malformed output after the existing
JSON retry behavior, or IDs outside the authorized catalog, the request fails
closed with a data error. It does not silently search every dataset.

For this version the full accessible catalog is placed in the routing prompt.
This keeps behavior transparent and testable. Candidate prefiltering can be
added later if prompt-size telemetry shows a need; it is outside this scope.

## Data flow

1. Validate the request and normalize an optional comma-separated
   `dataset_ids` string.
2. Resolve and authorize `chat_id`, if present.
3. Resolve the effective chat model.
4. If `dataset_ids` was supplied, authorize those IDs and mark the mode
   `manual`.
5. Otherwise, for stateless requests, load the accessible dataset catalog and
   call the dataset router; mark the mode `auto`.
6. For stateful requests without an override, validate the chat's dataset
   scope and mark the mode `chat`.
7. Validate that the final scope is nonempty, parsed, authorized, and embedding
   compatible.
8. Run the existing `rag_agent` flow using the final IDs.
9. Return the answer, chunk references, selection mode, and selected dataset
   trace.

Descriptions are routing metadata only. They never enter the answer context,
and they never appear as citations. Citations continue to come only from real
retrieved chunks.

## Logging

Server logs include `request_id`, selection mode, selected dataset IDs, router
latency, total latency, and success/failure. They do not include API keys,
provider credentials, full knowledge-base descriptions, or complete retrieved
content.

The one-click Bash and PowerShell scripts continue logging every HTTP request
and response. Their request log shows the comma-separated dataset override when
provided and shows that `dataset_ids` was omitted for automatic routing.

## Error handling

The endpoint returns a data error for:

- malformed or empty comma-separated `dataset_ids`;
- inaccessible, invalid, or empty manually selected datasets;
- no accessible parsed dataset for automatic routing;
- router output with no authorized selection;
- datasets that do not share a compatible embedding model;
- missing or invalid chat-model configuration.

Unexpected provider, database, and Agentic Search failures keep the current
exception response and `request_id` correlation behavior.

## Testing

Focused unit tests cover:

- omitted `dataset_ids` is accepted for stateless automatic routing;
- a comma-separated string is trimmed, deduplicated, and normalized;
- list, non-string, and comma-only values are rejected;
- only accessible valid datasets with parsed chunks enter the router catalog;
- authorized IDs, maximum selection count, confidence normalization, and
  embedding compatibility are enforced on router output;
- manual selection bypasses the router;
- stateful chat scope remains functional;
- the normalized response exposes `dataset_selection_mode` and
  `selected_datasets`;
- both scripts send one comma-separated dataset string or omit it for automatic
  routing;
- route-level validation and error mapping remain stable.

The implementation is verified with the focused API, service, script, and
Agentic Search test suites, Python compilation, PowerShell parsing, Bash syntax
validation, and `git diff --check`.

## Documentation

`README.agentic-search.md` will document automatic routing as the default,
manual comma-separated override examples, response routing fields, security
boundaries, failure modes, and DeepAgent/MCP calling guidance.
