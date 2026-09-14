"""Search tools: hybrid, vector, BM25, web, structured."""

import hashlib
import logging
import re

from common import settings

_LOG = logging.getLogger(__name__)


# Sentence terminators: Chinese 。！？；, English ! ? ;, newline, and a
# digit-guarded English period (so "3.14" / "v1.2" don't split).
_SENT_END = re.compile(r"[。！？；!?;]+|(?<!\d)\.(?!\d)")

# Table blocks are kept ATOMIC — never split by sentence terminators — so a
# whole table counts as one "sentence" for keyword matching / narrowing.
_HTML_TABLE = re.compile(r"<table\b[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL)
# Markdown table: a header row with a pipe, a separator row of dashes/colons/
# pipes, then zero+ body rows with a pipe.
_MD_TABLE = re.compile(
    r"^[ \t]*\|?[^\n]*\|[^\n]*\r?\n"
    r"[ \t]*\|?[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)+\|?[ \t]*\r?\n"
    r"(?:[ \t]*\|?[^\n]*\|[^\n]*\r?\n?)*",
    re.MULTILINE,
)


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """Non-overlapping ``(start, end)`` spans of table blocks, in order."""
    spans = [(m.start(), m.end()) for m in _HTML_TABLE.finditer(text)]
    spans += [(m.start(), m.end()) for m in _MD_TABLE.finditer(text)]
    spans.sort()
    merged: list[tuple[int, int]] = []
    last_end = -1
    for s, e in spans:
        if s < last_end:  # overlaps an already-kept span -> skip
            continue
        merged.append((s, e))
        last_end = e
    return merged


def _split_plain(text: str) -> list[str]:
    """Terminator-based sentence split, keeping each terminator attached."""
    sents: list[str] = []
    start = 0
    for m in _SENT_END.finditer(text):
        end = m.end()
        seg = text[start:end]
        if seg.strip():
            sents.append(seg)
        start = end
    if start < len(text):
        tail = text[start:]
        if tail.strip():
            sents.append(tail)
    return sents


def _split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences, keeping each terminator attached.

    Table blocks — HTML ``<table>...</table>`` and markdown tables — are treated
    as a single atomic sentence and are never split internally.
    """
    if not text:
        return []
    spans = _protected_spans(text)
    if not spans:
        return _split_plain(text)

    sents: list[str] = []
    pos = 0
    for s, e in spans:
        if s > pos:
            sents.extend(_split_plain(text[pos:s]))
        block = text[s:e]
        if block.strip():
            sents.append(block)
        pos = e
    if pos < len(text):
        sents.extend(_split_plain(text[pos:]))
    return sents


def _narrow_content(content: str, kwds: list[str]) -> str | None:
    """Return ``content`` narrowed to keyword sentences +/- 1 neighbour.

    Returns ``None`` when no keyword occurs anywhere in ``content``.
    """
    sents = _split_sentences(content)
    if not sents:
        return None
    keep: set[int] = set()
    matched = False
    for i, s in enumerate(sents):
        low = s.lower()
        if any(kw in low for kw in kwds):
            matched = True
            if i > 0:
                keep.add(i - 1)
            keep.add(i)
            if i + 1 < len(sents):
                keep.add(i + 1)
    if not matched:
        return None
    narrowed = "".join(sents[i] for i in sorted(keep)).strip()
    return "..." + _highlight_keywords(narrowed, kwds) + "..."


def _highlight_keywords(text: str, kwds: list[str]) -> str:
    terms = sorted({kw for kw in kwds if kw}, key=len, reverse=True)
    if not terms:
        return text
    pattern = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    return pattern.sub(lambda m: f"<em>{m.group(0)}</em>", text)


def _narrow_by_keywords(chunks: list[dict], keywords: str) -> list[dict]:
    """Narrow each chunk to its keyword-bearing sentences (+/- 1 neighbour) and
    drop keyword-less chunks.

    Keywords are the comma-separated terms (with close synonyms) produced by
    ``formalize``; matching is case-insensitive substring.
    """
    kwds = [k.strip().lower() for k in (keywords or "").split(",") if k.strip()]
    if not kwds or not chunks:
        return chunks
    if len(kwds) < 3:
        kwds = [k.strip().lower() for k in (keywords or "").split(" ") if k.strip()]
        _kwds = []
        for i in range(len(kwds) - 1):
            _kwds.append(kwds[i] + " " + kwds[i + 1])
        kwds = _kwds

    scored = [(ck, _narrow_content(ck.get("content_with_weight") or ck.get("content") or "", kwds)) for ck in chunks]
    out: list[dict] = []
    dedup: set[str] = set()
    for ck, nc in scored:
        if nc is not None:
            nc_hash = hashlib.md5(nc.encode("utf-8")).hexdigest()
            if nc_hash in dedup:
                continue
            dedup.add(nc_hash)
            ck["content_with_weight"] = nc
            if "content" in ck:
                ck["content"] = nc
            ck.pop("highlight", None)
            out.append(ck)
    return out


def _search_cache_key(effective_query: str, target_ids, top_n: int, doc_scope) -> tuple:
    """Key a retrieval by what actually determines its result.

    Includes the scope/limits so semantically different searches are never
    collapsed together — only a genuinely identical query is served from cache.
    """
    return (
        " ".join((effective_query or "").split()).lower(),
        tuple(sorted(target_ids or ())),
        int(top_n),
        tuple(sorted(doc_scope or ())),
    )


def _normalize(kbinfos: dict, tenant_ids: list[str] | str | None) -> dict:
    if not kbinfos:
        return {"chunks": [], "doc_aggs": []}
    if not tenant_ids:
        _LOG.warning("search: skip child retrieval because tenant_ids is empty")
        return kbinfos
    if isinstance(tenant_ids, str):
        tenant_ids = [tenant_ids]
    kbinfos["chunks"] = settings.retriever.retrieval_by_children(
        kbinfos.get("chunks", []),
        tenant_ids,
    )
    return kbinfos


async def hybrid_search(
    tools,
    query: str,
    kb_ids: list[str] | None = None,
    top_n: int = 12,
    doc_scope: list[str] | None = None,
    keywords: str = "",
    exclude_ids: list[str] | None = None,
) -> dict:
    """Search scoped passages, optionally skipping previously returned chunk IDs.

    Exclusions apply after child-to-parent normalization, not in the backend.
    Unseen search inspects at most four pages of at most 100 returned candidates;
    the backend's internal candidate/reranking work is governed by retrieval().
    """
    target_ids = tools.kb_ids if kb_ids is None else kb_ids
    if not set(target_ids or ()).issubset(set(tools.kb_ids or ())):
        return {"chunks": [], "doc_aggs": [], "error": "kb_ids exceed the authorized knowledge bases"}
    if not target_ids or top_n <= 0 or doc_scope == []:
        return {"chunks": [], "doc_aggs": []}
    if doc_scope is not None:
        from common.misc_utils import thread_pool_exec

        known = await thread_pool_exec(tools._filter_known_doc_ids, doc_scope)
        if set(doc_scope) != set(known):
            return {"chunks": [], "doc_aggs": [], "error": "doc_scope contains unknown or unauthorized documents"}
        if set(target_ids) != set(tools.kb_ids):
            for doc_id in dict.fromkeys(doc_scope):
                owner = await thread_pool_exec(tools._resolve_doc_tenant, doc_id)
                if not owner or owner[0] not in target_ids:
                    return {"chunks": [], "doc_aggs": [], "error": "doc_scope exceeds the requested knowledge bases"}
    _LOG.info(f'[Hybrid search] Searching the knowledge base for "{query}" (keywords: {keywords})')

    # Query expansion: append the formalized-question keywords + close synonyms
    # so hybrid/BM25 retrieval gets extra recall signal.
    effective_query = f"{query} {keywords}".strip() if keywords else query

    # Per-request dedup: an identical query+scope is retrieved at most once, so
    # e.g. pre_search and a claim search asking the same question don't repeat
    # the ES round-trip, child fetch and narrowing.
    cache = getattr(tools, "search_cache", None)
    cache_key = _search_cache_key(effective_query, target_ids, top_n, doc_scope)
    excluded = set(exclude_ids or ())
    if excluded:
        cache_key += (tuple(sorted(excluded)),)
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        _LOG.info(f"[Hybrid search] Already searched this — reusing the {len(cached.get('chunks', []))} passage(s) found earlier.")
        return cached

    embd_mdl = tools.embed_mdl
    vector_weight = 0.3 if embd_mdl else 0

    page_size = min(max(2 * top_n, 24), 100) if excluded else top_n
    max_pages = 4 if excluded else 1
    candidates_examined = 0
    found = []
    seen = set(excluded)
    for page in range(1, max_pages + 1):
        batch = await settings.retriever.retrieval(
            effective_query,
            embd_mdl,
            tools.tenant_ids,
            target_ids,
            page,
            page_size,
            0.2,
            vector_similarity_weight=vector_weight,
            aggs=True,
            highlight=False,
            doc_ids=doc_scope,
        )
        if excluded:
            batch = dict(batch or {"chunks": [], "doc_aggs": []})
            batch["chunks"] = batch.get("chunks", [])[:page_size]
        raw_count = len((batch or {}).get("chunks", []))
        candidates_examined += raw_count
        batch = _normalize(batch, tools.tenant_ids)
        if excluded:
            batch["chunks"] = [ck for ck in batch.get("chunks", []) if ck.get("chunk_id") not in seen]
        if keywords:
            batch["chunks"] = _narrow_by_keywords(batch.get("chunks", []), keywords)
        if not excluded:
            kbinfos = batch
            break
        if page == 1:
            kbinfos = dict(batch)
        for ck in batch.get("chunks", []):
            chunk_id = ck.get("chunk_id")
            if chunk_id and chunk_id not in seen:
                seen.add(chunk_id)
                found.append(ck)
                if len(found) >= top_n:
                    break
        # A reranked short/empty page does not imply that later backend
        # candidate blocks are empty. Exhaust only the explicit call budget.
        if len(found) >= top_n:
            break
    if excluded:
        kbinfos["chunks"] = found
        documents = {}
        for ck in found:
            doc_id = ck.get("doc_id")
            if doc_id:
                document = documents.setdefault(doc_id, {"doc_id": doc_id, "doc_name": ck.get("docnm_kwd", ""), "count": 0})
                document["count"] += 1
        kbinfos["doc_aggs"] = list(documents.values())
        kbinfos["search_metadata"] = {
            "exclusion_mode": "post_normalization",
            "candidate_budget": page_size * max_pages,
            "candidates_examined": candidates_examined,
            "retrieval_calls": page,
            "budget_exhausted": page == max_pages and len(found) < top_n,
        }
    if cache is not None:
        cache[cache_key] = kbinfos
    return kbinfos


async def vector_search(tools, query: str, kb_ids: list[str] | None = None, top_n: int = 12, keywords: str = "") -> dict:
    if not tools.embed_mdl:
        _LOG.warning("vector_search: no embed_mdl available")
        return {"chunks": [], "doc_aggs": []}

    _LOG.info(f'[Vector search] Searching by meaning for "{query}" (keywords: {keywords})')
    effective_query = f"{query} {keywords}".strip() if keywords else query
    target_ids = kb_ids or tools.kb_ids
    kbinfos = await settings.retriever.retrieval(
        effective_query,
        tools.embed_mdl,
        tools.tenant_ids,
        target_ids,
        1,
        top_n,
        0.2,
        vector_similarity_weight=1.0,
        aggs=False,
        highlight=False,
    )
    kbinfos = _normalize(kbinfos, tools.tenant_ids)
    if keywords:
        length = len(kbinfos["chunks"])
        kbinfos["chunks"] = _narrow_by_keywords(kbinfos.get("chunks", []), keywords)
        _LOG.info(f"[Vector search] Kept {len(kbinfos['chunks'])} of {length} passage(s) that actually mention the keywords.")
    return kbinfos


async def bm25_search(tools, query: str, kb_ids: list[str] | None = None, top_n: int = 12, keywords: str = "") -> dict:
    _LOG.info(f'[BM25 search] Searching by keyword for "{query}" (keywords: {keywords})')
    target_ids = kb_ids or tools.kb_ids
    effective_query = f"{query} {keywords}".strip() if keywords else query
    kbinfos = await settings.retriever.retrieval(
        effective_query,
        None,
        tools.tenant_ids,
        target_ids,
        1,
        top_n,
        0.0,
        vector_similarity_weight=0,
        aggs=False,
        highlight=False,
    )
    kbinfos = _normalize(kbinfos, tools.tenant_ids)
    if keywords:
        length = len(kbinfos["chunks"])
        kbinfos["chunks"] = _narrow_by_keywords(kbinfos.get("chunks", []), keywords)
        _LOG.info(f"[BM25 search] Kept {len(kbinfos['chunks'])} of {length} passage(s) that actually mention the keywords.")
    return kbinfos


async def web_search(tools, query: str, keywords: str = "") -> dict:
    if not tools.has_web():
        return {"chunks": [], "doc_aggs": []}

    _LOG.info(f'[Web search] Searching the web for "{query}"')
    try:
        from common.misc_utils import thread_pool_exec

        effective_query = f"{query} {keywords}".strip() if keywords else query
        tav_res = await thread_pool_exec(tools.tav.retrieve_chunks, effective_query)
        return {"chunks": tav_res.get("chunks", []), "doc_aggs": tav_res.get("doc_aggs", [])}
    except Exception:
        _LOG.exception("web_search failed")
        return {"chunks": [], "doc_aggs": []}


async def structured_query(tools, query: str, keywords: str = "", kb_ids: list[str] | None = None) -> dict:
    """Answer from the structured (tabular) KBs by translating the query to SQL.

    ``keywords`` is accepted for schema conformance but deliberately unused: the
    query is translated to SQL rather than keyword-matched, and the rows it
    returns are not prose to narrow.
    """
    _LOG.info(f'[Structured search] Querying the structured (table) data for "{query}"')
    sql_kbs = [kb for kb in tools.sql_kbs if kb_ids is None or kb.id in kb_ids]
    if not sql_kbs:
        return {"answer": "", "chunks": [], "doc_aggs": []}
    from api.db.services.dialog_service import use_sql

    tenant_id = sql_kbs[0].tenant_id
    sql_kb_ids = [kb.id for kb in sql_kbs]
    try:
        ans = await use_sql(query, tools.field_map, tenant_id, tools.chat_mdl, quota=True, kb_ids=sql_kb_ids)
    except Exception:
        _LOG.exception("structured_query failed")
        return {"answer": "", "chunks": [], "doc_aggs": []}
    if not ans:
        return {"answer": "", "chunks": [], "doc_aggs": []}
    ref = ans.get("reference") or {}
    return {
        "answer": ans.get("answer", "") or "",
        "chunks": ref.get("chunks") or [],
        "doc_aggs": ref.get("doc_aggs") or [],
    }
