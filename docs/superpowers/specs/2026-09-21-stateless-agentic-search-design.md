# Stateless Agentic Search API Design

## Goal

Allow DeepAgent and other external processes to invoke `POST /api/v1/agentic-search` without creating, discovering, or supplying a RAGFlow Chat Assistant ID.

## API contract

`chat_id` becomes optional. In stateless mode the minimum useful request is:

```json
{
  "query": "查询产品的机械手功能并给出引用",
  "dataset_ids": ["982c06185fc011f1a9d2a33ecabf0a06"]
}
```

The existing request fields remain available: `model`, `reasoning`, `top_n`, and `similarity_threshold`. `reasoning` defaults to `3`. When `model` is omitted, the service uses the authenticated tenant's default chat model.

Stateless requests must provide at least one non-empty `dataset_ids` entry. Searching every dataset owned by a tenant is not an implicit fallback because it would make scope, cost, and authorization behavior unpredictable.

`session_id` is rejected when `chat_id` is absent. A stateless response sets `chat_id` and `session_id` to `null`.

Requests that include `chat_id` retain the current behavior, including optional session continuation and request-scoped overrides.

## Execution

The service validates every requested dataset using the existing RAGFlow accessibility, parsed-chunk, and embedding-compatibility checks. It resolves the explicit model or tenant default model through the existing tenant model services.

For a stateless request it constructs an in-memory dialog object with the authenticated tenant ID, selected datasets, selected model, RAG retrieval defaults, and the standard knowledge-aware prompt containing `{knowledge}`. Request overrides are applied to this object only. No Dialog row is created or updated.

The service creates an in-memory conversation-shaped object for `structure_answer`, calls the existing `rag_agent(..., stream=False, reasoning=...)` path, and normalizes the final answer and references. It does not create or update a Conversation row.

## Response and errors

The response keeps the existing envelope and normalized fields:

```json
{
  "code": 0,
  "data": {
    "request_id": "...",
    "chat_id": null,
    "session_id": null,
    "answer": "...",
    "references": [],
    "reference_count": 0,
    "model": "...",
    "reasoning": 3,
    "elapsed_ms": 1000
  }
}
```

Validation rejects these combinations:

- no `chat_id` and no usable `dataset_ids`;
- `session_id` without `chat_id`;
- inaccessible, missing, or unparsed datasets;
- incompatible embedding models across requested datasets;
- an unknown or unavailable explicit/default chat model.

Unexpected execution errors continue to return `data.request_id` for log correlation. Bearer tokens and provider keys are never logged.

## Compatibility

The route and URL remain unchanged. Existing callers that send `chat_id` continue through the persisted Chat Assistant/session path. The PowerShell and Bash test scripts make `chat_id` optional and support stateless calls by passing one or more dataset IDs.

README examples lead with the stateless DeepAgent request and describe the Chat Assistant path as an optional stateful mode.

## Verification

Focused tests cover:

- validation of stateless and stateful field combinations;
- construction of an isolated temporary dialog;
- tenant-default model selection;
- no Dialog or Conversation persistence in stateless mode;
- normalized `null` chat/session IDs and references;
- unchanged stateful behavior;
- both smoke scripts operating without `chat_id`.

The existing Agentic Search regression suite remains part of final verification. A live 9380 smoke test is run after the deployed backend has been restarted with the new code.
