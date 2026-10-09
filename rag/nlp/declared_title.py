"""Bounded declared-title enrichment for document keyword indexes."""

import re

_HEADER = re.compile(r"^\s*(?:title|name|fullname)\s*:\s*(.*)$", re.IGNORECASE)
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_NOISE = frozenset(["title", "name", "fullname", "wikipedia", "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "by", "with", "from", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these", "those", "as", "into", "over", "under"])


def declared_title_terms(chunks: list[dict]) -> list[str]:
    """Read explicit labels in the first text chunk's first twenty lines."""
    text = next((str(chunk.get("content_with_weight") or "") for chunk in chunks
                 if not chunk.get("compile_kwd") and str(chunk.get("content_with_weight") or "").strip()), "")
    terms = []
    seen = set()
    for line in text[:8192].splitlines()[:20]:
        match = _HEADER.match(line)
        if not match:
            continue
        for word in _WORDS.findall(match[1][:512].lower()):
            if word in seen or word in _NOISE or word.isdecimal():
                continue
            if len(" ".join([*terms, word])) > 512:
                return terms
            seen.add(word)
            terms.append(word)
            if len(terms) == 20:
                return terms
    return terms


def enrich_declared_titles(chunks: list[dict], tokenizer) -> list[dict]:
    """Add title terms without altering original chunks' other indexed fields."""
    terms = declared_title_terms(chunks)
    if not terms:
        return chunks
    tokens = tokenizer.tokenize(" ".join(terms)).split()
    for chunk in chunks:
        if chunk.get("compile_kwd"):
            continue
        old = chunk.get("title_tks") or ""
        seen = set(old.split())
        extra = []
        for token in tokens:
            if token not in seen:
                extra.append(token)
                seen.add(token)
        if extra:
            chunk["title_tks"] = (old + " " + " ".join(extra)).strip()
            chunk["title_sm_tks"] = tokenizer.fine_grained_tokenize(chunk["title_tks"])
    return chunks
