#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="http://127.0.0.1:9380"
CHAT_ID=""
DATASET_IDS=""
MODEL=""
REASONING=3
TOP_N=8
SIMILARITY_THRESHOLD=0.2
TIMEOUT=300
LOG_PATH=""
SESSION_ID=""
API_KEY="${RAGFLOW_API_KEY:-}"
QUERY=""

usage() {
  cat <<'EOF'
Usage: test_agentic_search.sh --api-key KEY --query TEXT [options]
  --base-url URL       RAGFlow URL (default http://127.0.0.1:9380)
  --chat-id ID         Optional Chat Assistant ID for stateful mode
  --dataset-id IDS     Optional comma-separated dataset IDs; auto-route when omitted
  --model REF          Optional model reference; tenant default when omitted
  --reasoning 1..4     Agentic reasoning level (default 3)
  --top-n N            Retrieval result count (default 8)
  --threshold FLOAT    Similarity threshold (default 0.2)
  --session-id ID      Continue an existing session
  --timeout SEC        Request timeout (default 300)
  --log PATH           JSONL output path
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-key) API_KEY="$2"; shift 2 ;;
    --query) QUERY="$2"; shift 2 ;;
    --base-url) BASE_URL="${2%/}"; shift 2 ;;
    --chat-id) CHAT_ID="$2"; shift 2 ;;
    --dataset-id) DATASET_IDS="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --reasoning) REASONING="$2"; shift 2 ;;
    --top-n) TOP_N="$2"; shift 2 ;;
    --threshold) SIMILARITY_THRESHOLD="$2"; shift 2 ;;
    --session-id) SESSION_ID="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --log) LOG_PATH="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$API_KEY" ]] || { echo "Missing --api-key or RAGFLOW_API_KEY" >&2; exit 2; }
[[ -n "$QUERY" ]] || { echo "Missing --query" >&2; exit 2; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 2; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 2; }

if [[ -z "$LOG_PATH" ]]; then
  LOG_PATH="$(dirname "$0")/../logs/agentic-search-$(date +%Y%m%d-%H%M%S).jsonl"
fi
mkdir -p "$(dirname "$LOG_PATH")"

log_event() {
  local event="$1" payload="$2"
  jq -cn --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg event "$event" --argjson payload "$payload" \
    '{timestamp:$timestamp,event:$event}+ $payload' >> "$LOG_PATH"
}

BODY="$(jq -cn \
  --arg query "$QUERY" --arg chat "$CHAT_ID" --arg datasets "$DATASET_IDS" \
  --arg model "$MODEL" --arg session "$SESSION_ID" \
  --argjson reasoning "$REASONING" --argjson top_n "$TOP_N" --argjson threshold "$SIMILARITY_THRESHOLD" \
  '{query:$query,reasoning:$reasoning,top_n:$top_n,similarity_threshold:$threshold}
   + (if $datasets == "" then {} else {dataset_ids:$datasets} end)
   + (if $model == "" then {} else {model:$model} end)
   + (if $chat == "" then {} else {chat_id:$chat} end)
   + (if $session == "" then {} else {session_id:$session} end)')"
URI="$BASE_URL/api/v1/agentic-search"
log_event request "$(jq -cn --arg method POST --arg uri "$URI" --arg authorization 'Bearer <REDACTED_API_KEY>' --argjson body "$BODY" '{method:$method,uri:$uri,authorization:$authorization,body:$body}')"

STARTED="$(date +%s%3N)"
echo "[$(date +%H:%M:%S)] -> POST agentic_search"
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT
set +e
STATUS="$(curl -sS --max-time "$TIMEOUT" -X POST "$URI" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  --data "$BODY" -o "$RESPONSE_FILE" -w '%{http_code}')"
CURL_EXIT=$?
set -e
RESPONSE="$(cat "$RESPONSE_FILE")"
ELAPSED=$(( $(date +%s%3N) - STARTED ))
RESPONSE_JSON="$(jq -cn --arg raw "$RESPONSE" 'try ($raw | fromjson) catch $raw')"
log_event response "$(jq -cn --argjson status "${STATUS:-0}" --argjson elapsed "$ELAPSED" --argjson curl_exit "$CURL_EXIT" --argjson response "$RESPONSE_JSON" '{status:$status,elapsed_ms:$elapsed,curl_exit:$curl_exit,response:$response}')"

if [[ "$CURL_EXIT" -ne 0 ]]; then
  echo "curl failed with exit code $CURL_EXIT; response: $RESPONSE" >&2
  exit "$CURL_EXIT"
fi
if [[ "$STATUS" -lt 200 || "$STATUS" -ge 300 ]] || [[ "$(jq -r '.code // empty' <<<"$RESPONSE" 2>/dev/null)" != "0" ]]; then
  jq . <<<"$RESPONSE" >&2 2>/dev/null || echo "$RESPONSE" >&2
  exit 1
fi

echo "[$(date +%H:%M:%S)] <- success (${ELAPSED}ms)"
echo
echo "===== Agentic Search result ====="
jq -r '.data.answer' <<<"$RESPONSE"
echo
jq -r '"request_id=\(.data.request_id) session_id=\(.data.session_id) references=\(.data.reference_count)"' <<<"$RESPONSE"
jq -r '.data.references[:10][] | "- \(.document_name) | similarity=\(.similarity) | chunk=\(.chunk_id)"' <<<"$RESPONSE"
echo "Log: $LOG_PATH"
