"""Deterministic source and passage handles for web search citations."""

import hashlib


def _identity(prefix: str, text: str) -> str:
    return prefix + hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def normalize_web_evidence(result: dict) -> dict:
    """Preserve search data while deduplicating identical source passages.

    A source can yield different passages over time: its document handle stays
    stable but each distinct passage gets its own content handle. Different
    URLs remain distinct sources even when they quote identical text.
    """
    chunks = []
    aggregates = {}
    seen = set()
    old_aggs = {item.get("doc_id"): item for item in result.get("doc_aggs", [])}
    for chunk in result.get("chunks", []):
        content = str(chunk.get("content_with_weight") or "")
        if not content.strip():
            continue
        url = str(chunk.get("url") or "").strip().split("#", 1)[0]
        source = url or content
        doc_id = _identity("web_doc_", source)
        chunk_id = _identity("web_", source + "\0" + content)
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunks.append({**chunk, "doc_id": doc_id, "chunk_id": chunk_id})
        if doc_id not in aggregates:
            aggregates[doc_id] = {**old_aggs.get(chunk.get("doc_id"), {}), "doc_id": doc_id,
                                  "doc_name": chunk.get("docnm_kwd", ""), "url": chunk.get("url", ""), "count": 0}
        aggregates[doc_id]["count"] += 1
    return {**result, "chunks": chunks, "doc_aggs": list(aggregates.values())}
