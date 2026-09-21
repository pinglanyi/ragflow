# Agentic Search HTTP API Design

## Goal

Expose RAGFlow's existing Agentic Search implementation through the API server on port 9380 so external processes, including DeepAgent and future MCP tools, can invoke it through a stable JSON contract.

The endpoint must reuse RAGFlow's existing tenant authentication, model resolution, knowledge-base authorization, multimodal chunks, retrieval tools, citations, and session persistence. Request-scoped overrides must not mutate the stored Chat Assistant configuration.

## Endpoint

`POST /api/v1/agentic-search`

Authentication uses the existing RAGFlow bearer token mechanism.

### Request

```json
{
  "query": "请比较经典系列和卓越系列面板的机械手功能",
  "chat_id": "1c9dc6468a2511f1b194b520b0860b27",
  "session_id": "optional-existing-session-id",
  "dataset_ids": ["982c06185fc011f1a9d2a33ecabf0a06"],
  "model": "deepseek-v4-flash@parser@Tongyi-Qianwen",
  "reasoning": 3,
  "top_n": 8,
  "similarity_threshold": 0.2
}
```

Fields:

- `query`: required non-empty user question.
- `chat_id`: required Chat Assistant owned by the authenticated tenant. It provides the base prompt and default retrieval configuration.
- `session_id`: optional. If absent, a new session is created. If present, it must belong to `chat_id`.
- `dataset_ids`: optional request-scoped knowledge-base override. Every dataset must be accessible to the authenticated tenant. Omission uses the Chat Assistant's bound datasets.
- `model`: optional request-scoped model override. Omission uses the Chat Assistant's configured model.
- `reasoning`: optional integer from 1 to 4. Default is 3. Values map to the existing Agentic Search modes.
- `top_n` and `similarity_threshold`: optional request-scoped retrieval overrides.

Unknown fields are rejected so MCP callers receive immediate feedback when their schema is wrong.

### Success response

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "request_id": "uuid",
    "chat_id": "...",
    "session_id": "...",
    "answer": "...",
    "references": [
      {
        "chunk_id": "...",
        "dataset_id": "...",
        "document_id": "...",
        "document_name": "...",
        "content": "...",
        "similarity": 0.31,
        "positions": []
      }
    ],
    "reference_count": 1,
    "model": "deepseek-v4-flash@parser@Tongyi-Qianwen",
    "reasoning": 3,
    "elapsed_ms": 52032
  }
}
```

The response deliberately uses plain JSON and stable names suitable for an MCP tool result. It does not expose internal Python objects or raw provider responses.

## Architecture

The route lives in the existing 9380 Quart API application. A small service layer owns request validation, request-scoped dialog construction, execution, and response normalization.

The service loads the authenticated user's Chat Assistant, verifies the optional session, validates every dataset override, resolves the optional model, and creates an in-memory copy of the dialog configuration. Overrides are applied only to that copy. The service then invokes the same `rag_agent` path already used by `/api/v1/chat/completions`, collecting the final answer and reference chunks.

This avoids an HTTP loopback call and avoids PATCHing the Chat Assistant before each request. Two callers can therefore use different datasets or models at the same time without changing shared database state.

The existing `/api/v1/chat/completions` endpoint remains unchanged. The new endpoint is a purpose-built integration surface with a smaller schema and a normalized non-streaming response.

## Data flow

1. Authenticate the bearer token and obtain the tenant.
2. Validate the request schema and generate `request_id`.
3. Load and authorize `chat_id`.
4. Load or create the session and verify ownership.
5. Validate dataset and model overrides.
6. Copy the dialog and apply request-scoped overrides in memory.
7. Execute `rag_agent` with Agentic Search reasoning enabled.
8. Persist the user and assistant messages through the existing conversation path.
9. Normalize citations into the public response schema.
10. Log request ID, timing, selected resources, tool progress, and the final status.

## Logging

Each invocation logs one request ID across validation, model selection, retrieval, Agentic Search tools, and completion. Logs include IDs, durations, counts, and error categories. Authorization headers and provider API keys are never logged.

The HTTP response contains `request_id`, allowing an MCP caller to correlate failures with server logs. Tool-progress logs remain server-side; answer and citations are returned to the caller.

## Error handling

The endpoint uses the existing RAGFlow response envelope.

- Invalid schema or reasoning range: argument error.
- Unknown or unauthorized chat/session/dataset: authentication or not-found error without leaking other tenants' resource details.
- Invalid model: data error naming the requested model reference.
- Agentic Search failure: server error containing `request_id` and a concise message.
- Empty final answer: successful execution with an empty answer is treated as an execution error.

## Testing

Focused tests cover:

- Required fields and reasoning-range validation.
- Chat, session, and dataset authorization.
- Dataset/model overrides do not modify the stored dialog.
- Existing Chat Assistant defaults are used when overrides are omitted.
- Successful response normalization, including multimodal citation fields.
- Agent failure returns a request ID and does not leave a partial configuration mutation.
- Two concurrent requests with different dataset overrides remain isolated.

The PowerShell and Bash smoke-test scripts call the new endpoint, log every request and response as JSONL, and accept the query and all deployment-specific values as arguments.

## MCP integration boundary

The future MCP tool can map its input schema directly to this endpoint. A thin MCP adapter only needs to forward the bearer token and JSON body, then return `answer`, `references`, `session_id`, and `request_id`. No RAGFlow database or internal Python imports are required in the DeepAgent process.
