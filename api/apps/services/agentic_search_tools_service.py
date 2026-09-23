"""Mistral-style search primitives backed by authorized RAGFlow datasets."""

import io
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname


TOOL_NAMES = frozenset({"search", "open", "navigate", "read", "grep", "ingest", "delete"})
_FIELDS = {
    "search": {"query", "top_k", "exclude_ids", "dataset_ids", "dataset_names", "dataset_selection_mode"},
    "open": {"chunk_id", "window"},
    "navigate": {"source_id", "start_offset", "end_offset", "direction", "top_k"},
    "read": {"source_id", "start_offset", "end_offset", "top_k"},
    "grep": {"source_id", "pattern", "mode", "top_k"},
    "ingest": {"uri", "dataset_id"},
    "delete": {"source_id"},
}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def _number(value, name, *, minimum=0, maximum=10000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def validate_tool_request(name: str, payload: dict) -> dict:
    """Validate and normalize one native tool request without implicit scope widening."""
    if name not in TOOL_NAMES:
        raise ValueError("unknown Agentic Search tool")
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    unknown = set(payload) - _FIELDS[name]
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    if name == "search":
        query = _text(payload.get("query"), "query")
        top_k = _number(payload.get("top_k", 5), "top_k", minimum=1, maximum=20)
        excludes = payload.get("exclude_ids", [])
        if not isinstance(excludes, list) or len(excludes) > 200 or any(not isinstance(item, str) or not item.strip() for item in excludes):
            raise ValueError("exclude_ids must be a list of up to 200 chunk IDs")
        if "dataset_ids" in payload and "dataset_names" in payload:
            raise ValueError("Specify dataset_ids or dataset_names, not both")
        scope_key = "dataset_names" if "dataset_names" in payload else "dataset_ids"
        dataset_ids = payload.get(scope_key, "")
        if not isinstance(dataset_ids, str):
            raise ValueError(f"{scope_key} must be a comma-separated string")
        dataset_ids = list(dict.fromkeys(item.strip() for item in dataset_ids.split(",") if item.strip()))
        selection_mode = payload.get("dataset_selection_mode", "all")
        if selection_mode not in ("all", "auto"):
            raise ValueError("dataset_selection_mode must be all or auto")
        if selection_mode == "auto" and dataset_ids:
            raise ValueError("dataset_selection_mode=auto cannot be combined with dataset_names or dataset_ids")
        return {"query": query, "top_k": top_k, "exclude_ids": list(dict.fromkeys(excludes)),
                "dataset_ids": dataset_ids, "dataset_selection_mode": selection_mode}
    if name == "open":
        return {"chunk_id": _text(payload.get("chunk_id"), "chunk_id"),
                "window": _number(payload.get("window", 2), "window", maximum=20)}
    if name == "navigate":
        source_id = _text(payload.get("source_id"), "source_id")
        start = _number(payload.get("start_offset"), "start_offset")
        end = _number(payload.get("end_offset"), "end_offset")
        if end < start:
            raise ValueError("end_offset must be at least start_offset")
        direction = payload.get("direction")
        if direction not in ("next", "previous"):
            raise ValueError("direction must be next or previous")
        return {"source_id": source_id, "start_offset": start, "end_offset": end,
                "direction": direction, "top_k": _number(payload.get("top_k", 1), "top_k", minimum=1, maximum=20)}
    if name == "read":
        source_id = _text(payload.get("source_id"), "source_id")
        start = payload.get("start_offset")
        end = payload.get("end_offset")
        if start is not None:
            start = _number(start, "start_offset")
        if end is not None:
            end = _number(end, "end_offset")
        if start is not None and end is not None and end < start:
            raise ValueError("end_offset must be at least start_offset")
        return {"source_id": source_id, "start_offset": start, "end_offset": end,
                "top_k": _number(payload.get("top_k", 20), "top_k", minimum=1, maximum=20)}
    if name == "grep":
        source_id = _text(payload.get("source_id"), "source_id")
        pattern = _text(payload.get("pattern"), "pattern")
        if len(pattern) > 1000:
            raise ValueError("pattern is too long")
        mode = payload.get("mode", "phrase")
        if mode not in ("phrase", "term"):
            raise ValueError("mode must be phrase or term")
        return {"source_id": source_id, "pattern": pattern, "mode": mode,
                "top_k": _number(payload.get("top_k", 5), "top_k", minimum=1, maximum=20)}
    if name == "ingest":
        return {"uri": _text(payload.get("uri"), "uri"), "dataset_id": _text(payload.get("dataset_id"), "dataset_id")}
    return {"source_id": _text(payload.get("source_id"), "source_id")}


def normalize_chunk(chunk: dict) -> dict:
    """Expose a stable source identity and explicit ordinal coordinate system."""
    order = chunk.get("chunk_order")
    return {
        "id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
        "score": chunk.get("similarity"),
        "content": chunk.get("content_with_weight") or chunk.get("content") or "",
        "source_id": chunk.get("doc_id"),
        "start_offset": order,
        "end_offset": order,
        "metadata": {
            "dataset_id": chunk.get("kb_id"), "document_name": chunk.get("docnm_kwd"),
            "positions": chunk.get("positions") or chunk.get("position_int") or [],
            "image_id": chunk.get("image_id") or chunk.get("img_id") or "",
            "coordinate": "visible_chunk_ordinal",
            "navigable": order is not None,
        },
    }


def require_write_tools_enabled() -> None:
    """Fail closed unless the operator explicitly enables mutating tools."""
    if os.getenv("RAGFLOW_AGENTIC_SEARCH_WRITE_TOOLS_ENABLED", "").lower() != "true":
        raise PermissionError("Agentic Search ingest/delete tools are disabled")


def resolve_ingest_uri(uri: str) -> tuple[str, str]:
    """Resolve only operator-allowed local paths or URL hosts."""
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        allowed = {host.strip().lower() for host in os.getenv("RAGFLOW_AGENTIC_SEARCH_ALLOWED_URL_HOSTS", "").split(",") if host.strip()}
        if not parsed.hostname or parsed.hostname.lower() not in allowed or parsed.username or parsed.password:
            raise PermissionError("URI host is not allowed for ingestion")
        return "url", uri
    windows_drive = len(parsed.scheme) == 1 and Path(uri).is_absolute()
    if parsed.scheme not in ("", "file") and not windows_drive:
        raise ValueError("uri must be a local path, file URI, or HTTP(S) URL")
    root_setting = os.getenv("RAGFLOW_AGENTIC_SEARCH_INGEST_ROOT", "")
    if not root_setting:
        raise PermissionError("Local ingestion root is not configured")
    root = Path(root_setting).resolve()
    candidate = Path(url2pathname(unquote(parsed.path))) if parsed.scheme == "file" else Path(uri)
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise PermissionError("URI path is outside the allowed ingestion root")
    return "path", str(candidate)


def select_open_chunks(chunks: list[dict], chunk_id: str, window: int) -> list[dict]:
    """Expand around an anchor while preserving source reading order."""
    anchor = next((i for i, chunk in enumerate(chunks) if str(chunk.get("chunk_id") or chunk.get("id")) == chunk_id), None)
    if anchor is None:
        raise ValueError("chunk not found in the authorized document")
    return [normalize_chunk(chunk) for chunk in chunks[max(0, anchor - window):anchor + window + 1]]


def select_navigate_chunks(chunks: list[dict], start: int, end: int, direction: str, top_k: int) -> list[dict]:
    """Move from a known ordinal range to adjacent chunks."""
    if start >= len(chunks) or end >= len(chunks):
        raise ValueError("source offset is outside the document")
    selected = chunks[end + 1:end + 1 + top_k] if direction == "next" else chunks[max(0, start - top_k):start]
    return [normalize_chunk(chunk) for chunk in selected]


def select_read_chunks(chunks: list[dict], start: int | None, end: int | None, top_k: int) -> list[dict]:
    """Return a bounded inclusive ordinal range without context expansion."""
    lower = 0 if start is None else start
    upper = len(chunks) - 1 if end is None else end
    if lower >= len(chunks) and chunks:
        return []
    return [normalize_chunk(chunk) for chunk in chunks[lower:upper + 1][:top_k]]


def select_grep_chunks(chunks: list[dict], pattern: str, mode: str, top_k: int) -> list[dict]:
    """Find literal phrases or all whitespace-delimited terms in one document."""
    terms = [pattern.casefold()] if mode == "phrase" else pattern.casefold().split()
    matches = []
    for chunk in chunks:
        content = str(chunk.get("content_with_weight") or chunk.get("content") or "").casefold()
        if all(term in content for term in terms):
            matches.append(normalize_chunk(chunk))
            if len(matches) >= top_k:
                break
    return matches


async def _accessible_catalog(user_id: str) -> list[dict]:
    from api.apps.services.agentic_search_api_service import load_routable_datasets

    return await load_routable_datasets(user_id=user_id)


async def _auto_select_search_datasets(user_id: str, query: str, catalog: list[dict]) -> list[dict]:
    """Run the optional description-based router for an explicitly automatic search."""
    from api.apps.services.agentic_search_api_service import select_datasets
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.user_service import TenantService
    from common.constants import LLMType
    from common.misc_utils import thread_pool_exec

    found, tenant = await thread_pool_exec(TenantService.get_by_id, user_id)
    if not found or not tenant or not tenant.llm_id:
        raise ValueError("No default chat model configured for automatic dataset selection")
    model_config = await thread_pool_exec(
        resolve_model_config, tenant_id=user_id, model_type=LLMType.CHAT, model_ref=tenant.llm_id
    )
    return await select_datasets(tenant_id=user_id, query=query, datasets=catalog, model_config=model_config)


async def _search_scope(user_id: str, query: str, dataset_ids: list[str], selection_mode: str) -> tuple[list[str], str, list[dict]]:
    """Resolve visible IDs/names; an omitted scope means every visible parsed dataset."""
    catalog = await _accessible_catalog(user_id)
    if dataset_ids:
        from api.apps.services.agentic_search_api_service import validate_explicit_dataset_scope

        visible_ids = {row["id"] for row in catalog}
        by_name = {}
        for row in catalog:
            by_name.setdefault(row["name"], []).append(row["id"])
        resolved = []
        for token in dataset_ids:
            if token in visible_ids:
                resolved.append(token)
                continue
            matches = by_name.get(token, [])
            if len(matches) > 1:
                raise ValueError(f"ambiguous dataset name: {token}")
            if not matches:
                raise PermissionError("Dataset name or ID not found or not authorized")
            resolved.append(matches[0])
        resolved = list(dict.fromkeys(resolved))
        selected = await validate_explicit_dataset_scope(dataset_ids=resolved, user_id=user_id)
        return resolved, "manual", selected

    if selection_mode == "auto":
        selected = await _auto_select_search_datasets(user_id, query, catalog)
        return [row["id"] for row in selected], "auto", selected

    selected = [
        {"id": row["id"], "name": row["name"], "reason": "", "confidence": None}
        for row in catalog
    ]
    return [row["id"] for row in catalog], "all", selected


async def _search_embedding_groups(user_id: str, dataset_ids: list[str]) -> list[list[str]]:
    """Partition an all-dataset search so each vector call uses one embedding model."""
    catalog = {row["id"]: row for row in await _accessible_catalog(user_id)}
    groups = {}
    for dataset_id in dataset_ids:
        row = catalog.get(dataset_id)
        if row is None:
            raise PermissionError("Dataset not found or not authorized")
        embedding_group = (row.get("embd_id") or "").rsplit("@", 2)[0]
        groups.setdefault(embedding_group, []).append(dataset_id)
    return list(groups.values())


async def _authorized_tools(user_id: str, dataset_ids: list[str], *, embedding: bool = False):
    """Create a request-scoped RAGTools instance over verified knowledge bases."""
    from api.db.services.knowledgebase_service import KnowledgebaseService, validate_dataset_embedding_models
    from common.misc_utils import thread_pool_exec
    from rag.advanced_rag.agentic_rag import RAGTools

    if not dataset_ids:
        raise ValueError("No accessible parsed datasets are available")
    for dataset_id in dataset_ids:
        if not await thread_pool_exec(KnowledgebaseService.accessible, kb_id=dataset_id, user_id=user_id):
            raise PermissionError("Dataset not found or not authorized")
    kbs = await thread_pool_exec(KnowledgebaseService.get_by_ids, dataset_ids)
    if len(kbs) != len(dataset_ids):
        raise PermissionError("Dataset not found or not authorized")
    embd_mdl = None
    if embedding:
        from api.db.joint_services.tenant_model_service import resolve_model_config
        from api.db.services.llm_service import LLMBundle
        from common.constants import LLMType

        error = validate_dataset_embedding_models(kbs)
        if error:
            raise ValueError(error)
        if kbs[0].embd_id:
            config = await thread_pool_exec(
                resolve_model_config, kbs[0].tenant_id, LLMType.EMBEDDING, kbs[0].embd_id
            )
            embd_mdl = LLMBundle(kbs[0].tenant_id, config)
    tools = RAGTools(
        tenant_ids=list(dict.fromkeys(kb.tenant_id for kb in kbs)),
        chat_mdl=None, embed_mdl=embd_mdl, kb_ids=dataset_ids,
        include_field_mapped_kbs=True,
    )
    if set(tools.kb_ids) != set(dataset_ids):
        raise ValueError("Agentic Search tools require indexed text datasets")
    return tools


async def _tools_for_source(user_id: str, source_id: str):
    """Bind only the document's authorized dataset, denying guessed IDs."""
    from api.db.services.document_service import DocumentService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from common.misc_utils import thread_pool_exec

    docs = await thread_pool_exec(DocumentService.query, id=source_id)
    if not docs:
        raise ValueError("source document not found")
    dataset_id = docs[0].kb_id
    if not await thread_pool_exec(KnowledgebaseService.accessible, kb_id=dataset_id, user_id=user_id):
        raise PermissionError("source document is not authorized")
    return await _authorized_tools(user_id, [dataset_id])


async def _ordered_document(tools, source_id: str) -> list[dict]:
    return [chunk async for chunk in tools.iter_document_chunks(source_id)]


async def _source_for_chunk(user_id: str, chunk_id: str) -> str:
    """Find an anchor only in the caller's accessible indexes."""
    from common import settings
    from common.misc_utils import thread_pool_exec
    from rag.nlp import search

    for dataset in await _accessible_catalog(user_id):
        tools = await _authorized_tools(user_id, [dataset["id"]])
        kb = tools.kbs[0]
        row = await thread_pool_exec(
            settings.docStoreConn.get, chunk_id, search.index_name(kb.tenant_id), [kb.id]
        )
        if row and row.get("doc_id"):
            return row["doc_id"]
    raise ValueError("chunk not found in authorized datasets")


async def _search(user_id: str, options: dict) -> dict:
    from rag.advanced_rag.harness.tools.search import hybrid_search

    ids, mode, selected = await _search_scope(
        user_id, options["query"], options["dataset_ids"], options["dataset_selection_mode"]
    )
    groups = await _search_embedding_groups(user_id, ids)
    chunks = []
    group_metadata = []
    tools_by_source = {}
    for group_ids in groups:
        tools = await _authorized_tools(user_id, group_ids, embedding=True)
        result = await hybrid_search(
            tools, options["query"], top_n=options["top_k"], exclude_ids=options["exclude_ids"]
        )
        if result.get("error"):
            raise ValueError(result["error"])
        group_chunks = result.get("chunks") or []
        chunks.extend(group_chunks)
        group_metadata.append({
            "dataset_ids": group_ids,
            "search_metadata": result.get("search_metadata") or {},
        })
        for source_id in {chunk.get("doc_id") for chunk in group_chunks if chunk.get("doc_id")}:
            tools_by_source[source_id] = tools
    chunks.sort(key=lambda chunk: float(chunk.get("similarity") or 0), reverse=True)
    chunks = chunks[:options["top_k"]]
    orders = {}
    for source_id in {chunk.get("doc_id") for chunk in chunks if chunk.get("doc_id")}:
        try:
            tools = tools_by_source[source_id]
            orders[source_id] = {
                chunk["chunk_id"]: chunk["chunk_order"] for chunk in await _ordered_document(tools, source_id)
            }
        except ValueError:
            # A legacy document can still be searched even if it cannot be navigated safely.
            orders[source_id] = {}
    normalized = []
    for chunk in chunks:
        item = dict(chunk)
        chunk_id = item.get("chunk_id") or item.get("id")
        item["chunk_order"] = orders.get(item.get("doc_id"), {}).get(chunk_id)
        normalized.append(normalize_chunk(item))
    search_metadata = group_metadata[0]["search_metadata"] if len(group_metadata) == 1 else {
        "embedding_group_count": len(group_metadata), "groups": group_metadata,
    }
    return {"chunks": normalized, "selected_datasets": selected,
            "dataset_selection_mode": mode, "search_metadata": search_metadata,
            "coordinate": "visible_chunk_ordinal"}


async def _read_only_tool(name: str, user_id: str, options: dict) -> dict:
    if name == "search":
        return await _search(user_id, options)
    source_id = options.get("source_id")
    if name == "open":
        source_id = await _source_for_chunk(user_id, options["chunk_id"])
    tools = await _tools_for_source(user_id, source_id)
    chunks = await _ordered_document(tools, source_id)
    if name == "open":
        selected = select_open_chunks(chunks, options["chunk_id"], options["window"])
    elif name == "navigate":
        selected = select_navigate_chunks(chunks, options["start_offset"], options["end_offset"], options["direction"], options["top_k"])
    elif name == "read":
        selected = select_read_chunks(chunks, options["start_offset"], options["end_offset"], options["top_k"])
    else:
        selected = select_grep_chunks(chunks, options["pattern"], options["mode"], options["top_k"])
    return {"chunks": selected, "source_id": source_id, "coordinate": "visible_chunk_ordinal"}


async def _ingest_blobs(uri: str) -> list[tuple[str, bytes]]:
    """Load a bounded set of files from an explicitly allowed URI source."""
    from common.misc_utils import thread_pool_exec

    kind, location = resolve_ingest_uri(uri)
    limit = 20 * 1024 * 1024
    if kind == "url":
        import httpx

        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            async with client.stream("GET", location) as response:
                response.raise_for_status()
                if response.is_redirect:
                    raise PermissionError("Redirects are not allowed for ingestion URLs")
                data = bytearray()
                async for part in response.aiter_bytes():
                    data.extend(part)
                    if len(data) > limit:
                        raise ValueError("Ingest file exceeds 20 MiB")
        filename = Path(unquote(urlparse(location).path)).name or "download.txt"
        return [(filename, bytes(data))]

    root = Path(os.environ["RAGFLOW_AGENTIC_SEARCH_INGEST_ROOT"]).resolve()
    path = Path(location)
    if not path.exists():
        raise ValueError("Ingest path does not exist")
    paths = sorted(path.rglob("*")) if path.is_dir() else [path]
    files = [item for item in paths if item.is_file()]
    if not files or len(files) > 100:
        raise ValueError("Ingest path must contain 1 to 100 files")
    blobs = []
    for item in files:
        resolved = item.resolve()
        if not resolved.is_relative_to(root):
            raise PermissionError("Ingest path escaped allowed root")
        if resolved.stat().st_size > limit:
            raise ValueError("Ingest file exceeds 20 MiB")
        blobs.append((resolved.name, await thread_pool_exec(resolved.read_bytes)))
    return blobs


async def _ingest(user_id: str, options: dict) -> dict:
    from api.db.services.document_service import DocumentService
    from api.db.services.file_service import FileService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from common.misc_utils import thread_pool_exec

    dataset_id = options["dataset_id"]
    allowed = await thread_pool_exec(KnowledgebaseService.accessible4deletion, dataset_id, user_id)
    if not allowed:
        raise PermissionError("Dataset is not writable by this user")
    found, kb = await thread_pool_exec(KnowledgebaseService.get_by_id, dataset_id)
    if not found:
        raise ValueError("Dataset not found")
    blobs = await _ingest_blobs(options["uri"])
    uploaded = []
    for filename, content in blobs:
        file_obj = io.BytesIO(content)
        file_obj.filename = filename
        errors, files = await thread_pool_exec(FileService.upload_document, kb, [file_obj], user_id)
        if errors:
            raise ValueError("Document upload failed: " + "; ".join(errors))
        for doc, _ in files:
            await thread_pool_exec(DocumentService.run, kb.tenant_id, dict(doc), {})
            uploaded.append({"source_id": doc["id"], "dataset_id": dataset_id, "name": doc["name"], "parse_status": "QUEUED"})
    return {"documents": uploaded, "document_count": len(uploaded)}


async def _delete(user_id: str, options: dict) -> dict:
    from api.db.services.document_service import DocumentService
    from api.db.services.file_service import FileService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from common.misc_utils import thread_pool_exec

    source_id = options["source_id"]
    docs = await thread_pool_exec(DocumentService.query, id=source_id)
    if not docs:
        raise ValueError("Document not found")
    dataset_id = docs[0].kb_id
    allowed = await thread_pool_exec(KnowledgebaseService.accessible4deletion, dataset_id, user_id)
    if not allowed:
        raise PermissionError("Document is not writable by this user")
    errors = await thread_pool_exec(FileService.delete_docs, [source_id], user_id)
    if errors:
        raise ValueError("Document deletion failed: " + str(errors))
    return {"deleted": True, "source_id": source_id, "dataset_id": dataset_id}


async def execute_tool(name: str, payload: dict, *, user_id: str) -> dict:
    """Execute one authenticated tool request against the existing RAGFlow index."""
    options = validate_tool_request(name, payload)
    if name in ("ingest", "delete"):
        require_write_tools_enabled()
        return await (_ingest(user_id, options) if name == "ingest" else _delete(user_id, options))
    return await _read_only_tool(name, user_id, options)
