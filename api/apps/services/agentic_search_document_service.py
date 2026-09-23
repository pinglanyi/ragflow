"""Authorized document-name retrieval independent of chunk search."""

from collections import defaultdict
import logging


DESCRIPTION_FIELDS = ("description", "描述", "file_description")


def validate_request(payload: dict) -> dict:
    """Normalize file-name search arguments and reject ambiguous aliases."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    unknown = set(payload) - {"keyword", "query", "mode", "scan_meta", "top_k", "topkey", "dataset_names", "dataset_ids"}
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    if "keyword" in payload and "query" in payload:
        raise ValueError("Specify keyword or legacy query, not both")
    keyword = payload.get("keyword", payload.get("query"))
    if not isinstance(keyword, str) or not keyword.strip() or len(keyword.strip()) > 255:
        raise ValueError("keyword must be a nonempty file-name or description fragment of at most 255 characters")
    mode = payload.get("mode", "phrase")
    if mode not in ("phrase", "term"):
        raise ValueError("mode must be phrase or term")
    scan_meta = payload.get("scan_meta", False)
    if not isinstance(scan_meta, bool):
        raise ValueError("scan_meta must be a boolean")
    if "top_k" in payload and "topkey" in payload:
        raise ValueError("Specify top_k or topkey, not both")
    top_k = payload.get("top_k", payload.get("topkey", 5))
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 30:
        raise ValueError("top_k must be an integer between 1 and 30")
    if "dataset_names" in payload and "dataset_ids" in payload:
        raise ValueError("Specify dataset_names or dataset_ids, not both")
    scope_key = "dataset_names" if "dataset_names" in payload else "dataset_ids"
    scope = payload.get(scope_key, "")
    if not isinstance(scope, str):
        raise ValueError(f"{scope_key} must be a comma-separated string")
    return {
        "keyword": keyword.strip(),
        "mode": mode,
        "scan_meta": scan_meta,
        "top_k": top_k,
        "dataset_refs": list(dict.fromkeys(item.strip() for item in scope.split(",") if item.strip())),
    }


def resolve_scope(refs: list[str], catalog: list[dict]) -> list[dict]:
    """Resolve exact visible names or IDs; empty scope means all visible datasets."""
    if not refs:
        return catalog
    by_id = {row["id"]: row for row in catalog}
    by_name = defaultdict(list)
    for row in catalog:
        by_name[row["name"]].append(row)
    selected = []
    seen = set()
    for ref in refs:
        row = by_id.get(ref)
        if row is None:
            matches = by_name.get(ref, [])
            if len(matches) > 1:
                raise ValueError(f"ambiguous dataset name: {ref}")
            if not matches:
                raise PermissionError("Dataset name or ID not found or not authorized")
            row = matches[0]
        if row["id"] not in seen:
            seen.add(row["id"])
            selected.append(row)
    return selected


async def _visible_datasets(user_id: str) -> list[dict]:
    """List valid datasets visible to this user, including zero-chunk datasets."""
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.user_service import TenantService
    from common.misc_utils import thread_pool_exec

    joined = await thread_pool_exec(TenantService.get_joined_tenants_by_user_id, user_id)
    rows, _ = await thread_pool_exec(
        KnowledgebaseService.get_by_tenant_ids,
        [item["tenant_id"] for item in joined], user_id, 0, 0, "update_time", True, "",
    )
    return [{
        "id": row["id"], "name": row["name"], "tenant_id": row["tenant_id"],
        "chunk_num": row.get("chunk_num", 0), "embd_id": row.get("embd_id"),
    } for row in rows]


async def _retrieve_filename_candidates(selected: list[dict], keyword: str, top_k: int) -> dict[str, float]:
    """Recall documents through hybrid retrieval with dominant file-name fields."""
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.llm_service import LLMBundle
    from common import settings
    from common.constants import LLMType
    from rag.nlp import search

    indexed = [row for row in selected if row.get("chunk_num", 1) > 0]
    if not indexed:
        return {}
    candidate_limit = min(max(top_k * 10, 50), 300)
    query_fields = ["docnm_kwd^200", "title_tks^100", "title_sm_tks^50", "content_ltks"]
    groups = defaultdict(list)
    for row in indexed:
        groups[(row["tenant_id"], row.get("embd_id"))].append(row["id"])

    candidates = {}
    for (tenant_id, embd_id), dataset_ids in groups.items():
        try:
            embd_config = resolve_model_config(tenant_id, LLMType.EMBEDDING, embd_id)
            embd_mdl = LLMBundle(tenant_id, embd_config)
            ranks = await settings.retriever.retrieval(
                keyword,
                embd_mdl,
                [tenant_id],
                dataset_ids,
                1,
                candidate_limit,
                similarity_threshold=0.05,
                vector_similarity_weight=0.15,
                top=candidate_limit,
                aggs=False,
                rerank_mdl=None,
                highlight=False,
                rank_feature={},
                query_fields=query_fields,
                filename_token_weight=20,
            )
            for chunk in ranks.get("chunks", []):
                doc_id = chunk.get("document_id") or chunk.get("doc_id")
                if doc_id:
                    candidates[doc_id] = max(candidates.get(doc_id, float("-inf")), float(chunk.get("similarity", 0)))
        except Exception as exc:
            # A missing embedding configuration should not make filename lookup unusable.
            logging.warning("Hybrid source-file retrieval failed; falling back to BM25: %s", exc)
            result = await settings.retriever.search(
                {
                    "kb_ids": dataset_ids,
                    "page": 1,
                    "size": candidate_limit,
                    "topk": candidate_limit,
                    "question": keyword,
                    "available_int": 1,
                    "query_fields": query_fields,
                },
                [search.index_name(tenant_id)],
                dataset_ids,
                emb_mdl=None,
                highlight=False,
            )
            for chunk_id in result.ids:
                chunk = result.field.get(chunk_id) or {}
                doc_id = chunk.get("doc_id")
                if doc_id:
                    candidates[doc_id] = max(candidates.get(doc_id, float("-inf")), float(chunk.get("_score", 0) or 0))
    return candidates


def _text_matches(value: str, keyword: str, mode: str) -> bool:
    folded = (value or "").casefold()
    terms = [keyword.casefold()] if mode == "phrase" else keyword.casefold().split()
    return all(term in folded for term in terms)


async def _description_ids(selected: list[dict], keyword: str, mode: str, metadata_service, thread_pool_exec) -> list[str]:
    """Find document-level description matches without reading chunk content."""
    from common import settings

    terms = [keyword.casefold()] if mode == "phrase" else keyword.casefold().split()
    groups = defaultdict(list)
    for dataset in selected:
        groups[dataset.get("tenant_id")].append(dataset["id"])
    matched = []
    for kb_ids in groups.values():
        flattened = None

        async def scan(fields):
            nonlocal flattened
            if flattened is None:
                flattened = await thread_pool_exec(metadata_service.get_flatted_meta_by_kbs, kb_ids)
            ids = []
            for field in fields:
                for value, doc_ids in (flattened.get(field) or {}).items():
                    folded = str(value).casefold()
                    if all(term in folded for term in terms):
                        ids.extend(doc_ids)
            return ids

        if settings.DOC_ENGINE_INFINITY:
            # Infinity's JSON_CONTAINS tests exact values, not substrings.
            ids = await scan(DESCRIPTION_FIELDS)
        elif mode == "phrase":
            filters = [{"key": key, "op": "contains", "value": keyword} for key in DESCRIPTION_FIELDS]
            ids = await thread_pool_exec(metadata_service.filter_doc_ids_by_meta_pushdown, kb_ids, filters, "or", 10000)
            if ids is None:
                ids = await scan(DESCRIPTION_FIELDS)
        else:
            # Each description field must itself contain every whitespace-delimited term.
            ids = []
            for field in DESCRIPTION_FIELDS:
                filters = [{"key": field, "op": "contains", "value": term} for term in terms]
                field_ids = await thread_pool_exec(
                    metadata_service.filter_doc_ids_by_meta_pushdown, kb_ids, filters, "and", 10000
                )
                if field_ids is None:
                    field_ids = await scan((field,))
                ids.extend(field_ids)
        matched.extend(ids)
    return list(dict.fromkeys(matched))


def _name_rank(name: str, keyword: str, mode: str) -> int:
    lowered = (name or "").casefold()
    needle = keyword.casefold()
    if lowered == needle:
        return 0
    if mode == "phrase":
        if lowered.startswith(needle):
            return 1
        if needle in lowered:
            return 2
        return 4
    terms = needle.split()
    if terms and all(term in lowered for term in terms):
        return 1
    if any(term in lowered for term in terms):
        return 3
    return 4


async def find_source_files(payload: dict, *, user_id: str) -> dict:
    """Search one document record per file and return trusted storage coordinates."""
    from api.db.services.doc_metadata_service import DocMetadataService
    from api.db.services.document_service import DocumentService
    from common.misc_utils import thread_pool_exec

    options = validate_request(payload)
    selected = resolve_scope(options["dataset_refs"], await _visible_datasets(user_id))
    result = {
        "keyword": options["keyword"],
        "mode": options["mode"],
        "scan_meta": options["scan_meta"],
        "documents": [],
        "count": 0,
        "searched_dataset_count": len(selected),
    }
    if not selected:
        return result
    dataset_ids = [row["id"] for row in selected]
    retrieval_scores = await _retrieve_filename_candidates(selected, options["keyword"], options["top_k"])
    retrieval_ids = list(retrieval_scores)
    retrieval_rows = await thread_pool_exec(
        DocumentService.get_name_retrieval_documents, dataset_ids, retrieval_ids
    ) if retrieval_ids else []
    # Chunkless documents cannot appear in the full-text index, so query only
    # that bounded subset in SQL and merge it with indexed candidates.
    unparsed_rows = await thread_pool_exec(
        DocumentService.search_by_name, dataset_ids, options["keyword"], options["mode"], options["top_k"],
        unparsed_only=True,
    )
    name_rows = list({row["id"]: row for row in [*retrieval_rows, *unparsed_rows]}.values())
    description_ids = await _description_ids(
        selected, options["keyword"], options["mode"], DocMetadataService, thread_pool_exec
    ) if options["scan_meta"] else []
    description_rows = await thread_pool_exec(
        DocumentService.get_name_retrieval_documents, dataset_ids, description_ids
    ) if description_ids else []
    by_id = {row["id"]: row for row in description_rows}
    by_id.update({row["id"]: row for row in name_rows})
    retrieval_set = {row["id"] for row in retrieval_rows}
    filename_set = {
        row["id"] for row in name_rows
        if _text_matches(row.get("name") or "", options["keyword"], options["mode"])
    }
    description_set = {row["id"] for row in description_rows}
    rows = sorted(
        by_id.values(),
        key=lambda row: (
            min(_name_rank(row["name"], options["keyword"], options["mode"]) if row["id"] in filename_set else 4,
                2 if row["id"] in description_set else 4),
            -retrieval_scores.get(row["id"], 0),
            (row["name"] or "").casefold(), row["id"],
        ),
    )[:options["top_k"]]
    ids_by_dataset = defaultdict(list)
    for row in rows:
        if row["kb_id"] not in dataset_ids:
            raise ValueError("Document search returned a dataset outside the authorized scope")
        ids_by_dataset[row["kb_id"]].append(row["id"])
    metadata = {}
    for dataset_id, doc_ids in ids_by_dataset.items():
        metadata[dataset_id] = await thread_pool_exec(DocMetadataService.get_metadata_for_documents, doc_ids, dataset_id)
    names = {row["id"]: row["name"] for row in selected}
    for row in rows:
        dataset_id, doc_id = row["kb_id"], row["id"]
        custom = metadata.get(dataset_id, {}).get(doc_id) or {}
        metafield = dict(custom) if isinstance(custom, dict) else {}
        metafield.update({
            "datasetid": dataset_id,
            "docid": doc_id,
            "dataset_id": dataset_id,
            "doc_id": doc_id,
            "location": row.get("location"),
            "dataset_name": names[dataset_id],
        })
        result["documents"].append({
            "file_name": row["name"],
            "metafield": metafield,
            "matched_by": [source for source, ids in (
                ("file_name", filename_set),
                ("description", description_set),
                ("retrieval", retrieval_set - filename_set),
            ) if doc_id in ids],
        })
    result["count"] = len(result["documents"])
    return result


# Compatibility for deployments that imported the original internal name.
retrieve_documents_by_name = find_source_files
