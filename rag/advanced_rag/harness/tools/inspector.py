"""Inspect indexed source documents, keeping their original citation identities."""

from collections import deque
from copy import deepcopy


def _limit(value: int, name: str, maximum: int, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _anchor_document(tools, chunk_id: str) -> str:
    for chunk in tools.kbinfos.get("chunks", []):
        if _chunk_id(chunk) == chunk_id and chunk.get("doc_id"):
            return chunk["doc_id"]
    raise ValueError("Unknown chunk_id: use an indexed chunk returned by search or navigation")


async def open_context(tools, chunk_id: str, width: int = 500) -> dict:
    """Read anchor and whole neighbours up to width characters per side.

    At least one neighbour per side is included when present; a single chunk may
    exceed width. Expansion is additionally bounded to 20 chunks per side.
    """
    _limit(width, "width", 20000)
    doc_id = _anchor_document(tools, chunk_id)
    previous = deque(maxlen=20)
    output = []
    following_chars = 0
    following_count = 0
    found = False
    async for chunk in tools.iter_document_chunks(doc_id):
        if not found:
            if _chunk_id(chunk) != chunk_id:
                previous.append(chunk)
                continue
            before = []
            chars = 0
            for item in reversed(previous):
                before.append(item)
                chars += len(item.get("content_with_weight", ""))
                if chars >= width:
                    break
            output = list(reversed(before)) + [chunk]
            found = True
        else:
            output.append(chunk)
            following_count += 1
            following_chars += len(chunk.get("content_with_weight", ""))
            if following_chars >= width or following_count >= 20:
                break
    if not found:
        raise ValueError("Anchor no longer exists in the document; search again")
    return _result(output)


async def compare_sources(tools, chunk_ids: list[str]) -> dict:
    """Return already collected evidence for cross-source comparison."""
    return _result([c for c in tools.kbinfos.get("chunks", []) if _chunk_id(c) in chunk_ids])


async def grep_within(tools, doc_id: str, pattern: str, mode: str = "phrase", top_k: int = 5) -> dict:
    """Match a literal phrase, or all whitespace-separated terms, in indexed chunks.

    Matching is case-insensitive and chunk-local, not regex. Return full source
    chunks so table structure, VLM text and citation positions remain intact.
    """
    _limit(top_k, "top_k", 20)
    if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > 1000:
        raise ValueError("pattern must contain between 1 and 1000 characters")
    if mode not in ("phrase", "term"):
        raise ValueError("mode must be phrase or term")
    terms = [pattern.strip().casefold()] if mode == "phrase" else pattern.casefold().split()
    matches = []
    async for chunk in tools.iter_document_chunks(doc_id):
        text = chunk.get("content_with_weight", "").casefold()
        if all(term in text for term in terms):
            matches.append(chunk)
            if len(matches) >= top_k:
                break
    return _result(matches)


async def request_adjacent(tools, chunk_id: str, direction: str = "next", count: int = 3) -> dict:
    """Read actual source neighbours, including chunks not returned by search."""
    _limit(count, "count", 20)
    if direction not in ("prev", "next"):
        raise ValueError("direction must be prev or next")
    doc_id = _anchor_document(tools, chunk_id)
    previous = deque(maxlen=count)
    output = []
    found = False
    async for chunk in tools.iter_document_chunks(doc_id):
        if not found:
            if _chunk_id(chunk) != chunk_id:
                previous.append(chunk)
                continue
            found = True
            if direction == "prev":
                return _result(list(previous))
        else:
            output.append(chunk)
            if len(output) == count:
                break
    if not found:
        raise ValueError("Anchor no longer exists in the document; search again")
    return _result(output)


async def read_document(tools, doc_id: str, start: int = 0, count: int = 5) -> dict:
    """Read by zero-based visible source chunk ordinal, not PDF page or character offset."""
    _limit(start, "start", 9999, minimum=0)
    _limit(count, "count", 20)
    output = []
    index = 0
    async for chunk in tools.iter_document_chunks(doc_id):
        if index >= start:
            output.append(chunk)
            if len(output) == count:
                break
        index += 1
    result = _result(output)
    result["metadata"] = {"next_start": start + len(output), "coordinate": "visible_chunk_ordinal"}
    return result


def _chunk_id(chunk: dict) -> str:
    return str(chunk.get("chunk_id") or chunk.get("id") or "")


def _result(chunks: list[dict]) -> dict:
    chunks = deepcopy(chunks)
    docs = {}
    for chunk in chunks:
        if chunk.get("doc_id"):
            docs.setdefault(chunk["doc_id"], {"doc_id": chunk["doc_id"], "doc_name": chunk.get("docnm_kwd", "")})
    return {"chunks": chunks, "doc_aggs": list(docs.values())}
