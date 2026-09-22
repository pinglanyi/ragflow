"""Authorized document-name retrieval independent of chunk search."""

from collections import defaultdict


DESCRIPTION_FIELDS = ("description", "描述", "file_description")


def validate_request(payload: dict) -> dict:
    """Normalize file-name search arguments and reject ambiguous aliases."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    unknown = set(payload) - {"query", "top_k", "topkey", "dataset_names", "dataset_ids"}
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 255:
        raise ValueError("query must be a nonempty file-name or description fragment of at most 255 characters")
    if "top_k" in payload and "topkey" in payload:
        raise ValueError("Specify top_k or topkey, not both")
    top_k = payload.get("top_k", payload.get("topkey", 5))
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        raise ValueError("top_k must be an integer between 1 and 20")
    if "dataset_names" in payload and "dataset_ids" in payload:
        raise ValueError("Specify dataset_names or dataset_ids, not both")
    scope_key = "dataset_names" if "dataset_names" in payload else "dataset_ids"
    scope = payload.get(scope_key, "")
    if not isinstance(scope, str):
        raise ValueError(f"{scope_key} must be a comma-separated string")
    return {
        "query": query.strip(),
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
    return [{"id": row["id"], "name": row["name"], "tenant_id": row["tenant_id"]} for row in rows]


async def _description_ids(selected: list[dict], query: str, metadata_service, thread_pool_exec) -> list[str]:
    """Find document-level description matches without reading chunk content."""
    from common import settings

    groups = defaultdict(list)
    for dataset in selected:
        groups[dataset.get("tenant_id")].append(dataset["id"])
    filters = [{"key": key, "op": "contains", "value": query} for key in DESCRIPTION_FIELDS]
    matched = []
    for kb_ids in groups.values():
        # Infinity's JSON_CONTAINS tests exact values, not substrings. Scan its
        # document metadata to preserve the API's contains semantics.
        ids = None if settings.DOC_ENGINE_INFINITY else await thread_pool_exec(
            metadata_service.filter_doc_ids_by_meta_pushdown, kb_ids, filters, "or", 10000
        )
        if ids is None:
            # Backends without push-down still have a correct, slower path.
            flattened = await thread_pool_exec(metadata_service.get_flatted_meta_by_kbs, kb_ids)
            ids = []
            for field in DESCRIPTION_FIELDS:
                for value, doc_ids in (flattened.get(field) or {}).items():
                    if query.casefold() in str(value).casefold():
                        ids.extend(doc_ids)
        matched.extend(ids)
    return list(dict.fromkeys(matched))


def _name_rank(name: str, query: str) -> int:
    lowered = (name or "").casefold()
    needle = query.casefold()
    if lowered == needle:
        return 0
    if lowered.startswith(needle):
        return 1
    return 3


async def retrieve_documents_by_name(payload: dict, *, user_id: str) -> dict:
    """Search one document record per file and return trusted storage coordinates."""
    from api.db.services.doc_metadata_service import DocMetadataService
    from api.db.services.document_service import DocumentService
    from common.misc_utils import thread_pool_exec

    options = validate_request(payload)
    selected = resolve_scope(options["dataset_refs"], await _visible_datasets(user_id))
    result = {
        "query": options["query"],
        "documents": [],
        "count": 0,
        "searched_dataset_count": len(selected),
    }
    if not selected:
        return result
    dataset_ids = [row["id"] for row in selected]
    name_rows = await thread_pool_exec(DocumentService.search_by_name, dataset_ids, options["query"], options["top_k"])
    description_ids = await _description_ids(selected, options["query"], DocMetadataService, thread_pool_exec)
    description_rows = await thread_pool_exec(
        DocumentService.get_name_retrieval_documents, dataset_ids, description_ids
    ) if description_ids else []
    by_id = {row["id"]: row for row in description_rows}
    by_id.update({row["id"]: row for row in name_rows})
    name_ids = {row["id"] for row in name_rows}
    description_set = {row["id"] for row in description_rows}
    rows = sorted(
        by_id.values(),
        key=lambda row: (
            min(_name_rank(row["name"], options["query"]) if row["id"] in name_ids else 4,
                2 if row["id"] in description_set else 4),
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
            "matched_by": [source for source, ids in (("file_name", name_ids), ("description", description_set)) if doc_id in ids],
        })
    result["count"] = len(result["documents"])
    return result
