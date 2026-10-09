"""Bounded document metadata selection shared by Python agent and HTTP tools.

Dataset IDs must be authorized by the caller before invoking this module.
"""

import json
import math

_OPS = {"=", "contains", "not contains", "start with", "end with", "in", "not in", "empty", "not empty"}
_MAX_RESULT_CHARS = 60000
_MAX_MATCHES = 10000


def validate_metadata_filters(filters, logic="and"):
    """Reject invalid filters instead of silently dropping their conditions."""
    if logic not in ("and", "or"):
        raise ValueError("logic must be and or or")
    if not isinstance(filters, list) or not 1 <= len(filters) <= 10:
        raise ValueError("filters must contain 1 to 10 conditions")
    normalized = []
    for condition in filters:
        if not isinstance(condition, dict) or set(condition) - {"key", "op", "value"}:
            raise ValueError("Each filter must contain only key, op and value")
        key, op = condition.get("key"), condition.get("op")
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            raise ValueError("metadata key must be a nonempty string of at most 256 characters")
        if not isinstance(op, str) or op not in _OPS:
            raise ValueError("Unsupported metadata operator")
        value = condition.get("value")
        if op in ("empty", "not empty"):
            if value is not None:
                raise ValueError("empty/not empty filters take no value")
        elif op in ("in", "not in"):
            if not isinstance(value, list) or not 1 <= len(value) <= 50 or any(not _scalar(item) for item in value):
                raise ValueError("in/not in require 1 to 50 scalar values")
        elif not _scalar(value) or (op != "=" and not isinstance(value, str)):
            raise ValueError("String operators require one string; equality requires a scalar value")
        normalized.append({"key": key.strip(), "op": op, "value": value})
    if len(json.dumps(normalized, ensure_ascii=False)) > 8000:
        raise ValueError("Metadata conditions exceed 8000 characters")
    return normalized


def _scalar(value):
    return (isinstance(value, str) and len(value) <= 2000) or (
        isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) <= 1e308 and math.isfinite(value)
    )


def _ids(values):
    if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) or not value.strip() for value in values):
        raise RuntimeError("Metadata index returned an invalid document ID")
    return list(dict.fromkeys(values))


def _metadata_preview(metadata):
    """Keep a bounded, valid JSON object; signal any omitted field or value."""
    preview = {}
    truncated = False
    for key, value in metadata.items():
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        if len(encoded) > 2000:
            value = encoded[:1900] + "… [truncated]"
            truncated = True
        if len(str(key)) > 256 or len(preview) >= 30:
            truncated = True
            continue
        candidate = {**preview, str(key): value}
        if len(json.dumps(candidate, ensure_ascii=False, default=str)) > 8000:
            truncated = True
            continue
        preview = candidate
    return preview, truncated


async def select_metadata_documents(kb_ids, filters, logic="and", *, doc_scope=None, limit=50):
    """Return valid scoped document handles and metadata without content search.

    Queries run per dataset because the metadata index belongs to its tenant.
    No matches, no metadata and unknown fields have distinct result reasons.
    Backend failures propagate rather than masquerading as empty selections.
    """
    filters = validate_metadata_filters(filters, logic)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be an integer between 1 and 200")
    kb_ids = _ids(kb_ids)
    scope = set(_ids(doc_scope)) if doc_scope is not None else None
    result = {"kind": "metadata_search", "doc_ids": [], "documents": [], "filters": filters,
              "logic": logic, "available_fields": [], "truncated": False, "reason": "no_match"}
    if not kb_ids or scope == set():
        return result

    from api.db.services.doc_metadata_service import DocMetadataService
    from api.db.services.document_service import DocumentService
    from common.metadata_utils import meta_filter
    from common.misc_utils import thread_pool_exec

    fields_by_kb = {}
    for kb_id in kb_ids:
        fields_by_kb[kb_id] = set(await thread_pool_exec(DocMetadataService.get_metadata_keys_by_kbs, [kb_id], strict=True))
    available = sorted(set().union(*fields_by_kb.values()))
    result["available_fields"] = [field[:256] for field in available[:100]]
    result["truncated"] = len(available) > 100
    if not available:
        result["reason"] = "no_metadata"
        return result
    if any(condition["key"] not in available for condition in filters):
        result["reason"] = "unknown_field"
        return result

    seen = set()
    for kb_id in kb_ids:
        doc_ids = await thread_pool_exec(DocMetadataService.filter_doc_ids_by_meta_pushdown, [kb_id], filters, logic, limit=_MAX_MATCHES)
        if doc_ids is None:
            flattened = await thread_pool_exec(DocMetadataService.get_flatted_meta_by_kbs, [kb_id], strict=True)
            # Flattened metadata stores value keys as strings. Normalize only
            # this new selector's fallback; preserve legacy filter semantics.
            fallback_filters = []
            for condition in filters:
                value = condition["value"]
                if condition["op"] == "=" and isinstance(value, (int, float)):
                    value = str(value)
                elif condition["op"] in ("in", "not in"):
                    value = [str(item) if isinstance(item, (int, float)) else item for item in value]
                fallback_filters.append({**condition, "value": value})
            doc_ids = meta_filter(flattened, fallback_filters, logic) or []
        doc_ids = _ids(doc_ids)
        result["truncated"] |= len(doc_ids) >= _MAX_MATCHES
        doc_ids = [doc for doc in doc_ids if doc not in seen and (scope is None or doc in scope)]
        if not doc_ids:
            continue
        documents = await thread_pool_exec(DocumentService.get_name_retrieval_documents, [kb_id], doc_ids)
        documents = {doc["id"]: doc for doc in documents if doc.get("kb_id") == kb_id and doc.get("id") in doc_ids}
        valid_ids = [doc for doc in doc_ids if doc in documents]
        if not valid_ids:
            continue
        remaining = limit - len(result["documents"])
        result["truncated"] |= len(valid_ids) > remaining
        selected = valid_ids[:remaining]
        if not selected:
            break
        metadata = await thread_pool_exec(DocMetadataService.get_metadata_for_documents, selected, kb_id, strict=True)
        for doc_id in selected:
            preview, clipped = _metadata_preview(metadata.get(doc_id, {}))
            result["truncated"] |= clipped
            item = {"doc_id": doc_id, "dataset_id": kb_id, "name": str(documents[doc_id].get("name") or "")[:1000], "metadata": preview}
            if clipped:
                item["metadata_truncated"] = True
            candidate = {**result, "doc_ids": [*result["doc_ids"], doc_id], "documents": [*result["documents"], item]}
            if len(json.dumps(candidate, ensure_ascii=False, default=str)) > _MAX_RESULT_CHARS - 100:
                result["truncated"] = True
                result["reason"] = "matched"
                return result
            seen.add(doc_id)
            result["doc_ids"].append(doc_id)
            result["documents"].append(item)
    if result["doc_ids"]:
        result["reason"] = "matched"
    return result
