"""Submission orchestration for document-scoped multimodal jobs."""

import logging
from pathlib import Path
from time import monotonic

from peewee import IntegrityError

from api.db.db_models import DB, MultimodalJob, Task
from api.db.joint_services.tenant_model_service import resolve_model_config
from api.db.services.document_service import DocumentService
from api.db.services.file_service import FileService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.multimodal_job_service import MultimodalJobService as Jobs
from api.db.services.multimodal_job_service import build_config
from common.constants import LLMType

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, message, status=400, data=None):
        super().__init__(message)
        self.status = status
        self.data = data


def _dataset(tenant_id, dataset_id):
    rows = KnowledgebaseService.query(id=dataset_id, tenant_id=tenant_id)
    if not rows:
        raise ApiError("Dataset not found", 404)
    return rows[0]


def _config(tenant_id, kb, doc_config, options, filename):
    try:
        config = build_config(kb.parser_config, doc_config, options, filename)
        model = resolve_model_config(tenant_id, LLMType.VISION, config["multimodal"]["model"])
        if not model.get("api_base"):
            raise ValueError("An OpenAI-compatible vision endpoint is required")
        return config
    except (LookupError, ValueError, TypeError) as exc:
        # Model lookup exceptions may contain private provider details.
        if isinstance(exc, LookupError):
            raise ApiError("Registered vision model not found or unavailable") from exc
        raise ApiError(str(exc)) from exc


@DB.connection_context()
def submit(tenant_id, dataset_id, document_id, options):
    kb = _dataset(tenant_id, dataset_id)
    rows = DocumentService.query(id=document_id, kb_id=dataset_id)
    if not rows:
        raise ApiError("Document not found", 404)
    doc = rows[0]
    if doc.pipeline_id or getattr(kb, "pipeline_id", ""):
        raise ApiError("Switch the document/dataset from Pipeline to direct parsing first", 409)
    config = _config(tenant_id, kb, doc.parser_config, options, doc.name)
    base_parser_id = str(getattr(doc, "parser_id", "") or getattr(kb, "parser_id", "") or "naive")
    config.setdefault("ext", {})["_multimodal_base_parser_id"] = base_parser_id
    Jobs.refresh_document(document_id)
    # Refresh may recover a stale run flag after an interrupted submission.
    rows = DocumentService.query(id=document_id, kb_id=dataset_id)
    if not rows:
        raise ApiError("Document not found", 404)
    doc = rows[0]
    active = MultimodalJob.get_or_none(MultimodalJob.active_document_id == document_id)
    if active:
        raise ApiError("Document already has an active multimodal job", 409, Jobs.response(active))
    if str(doc.run) == "1" or Task.select().where((Task.doc_id == document_id) & (Task.progress >= 0) & (Task.progress < 1)).exists():
        raise ApiError("Document already has active parsing tasks", 409)
    try:
        # A unique nullable claim survives nested service connection contexts and API restarts.
        job = Jobs.create(tenant_id, dataset_id, document_id, config)
    except IntegrityError as exc:
        active = MultimodalJob.get_or_none(MultimodalJob.active_document_id == document_id)
        if not active:
            raise
        raise ApiError("Document already has an active multimodal job", 409, Jobs.response(active)) from exc
    parser_id = "picture" if Path(doc.name).suffix.lower() in Jobs.IMAGE_SUFFIXES else base_parser_id
    try:
        DocumentService.clear_chunk_num_when_rerun(document_id)
        DocumentService.update_by_id(document_id, {"parser_config": config, "parser_id": parser_id, "run": "1", "progress": 0, "progress_msg": "", "chunk_num": 0, "token_num": 0})
        task_doc = doc.to_dict()
        task_doc.update(parser_config=config, parser_id=parser_id, _multimodal_job_id=job.id)
        current = DocumentService.run(tenant_id, task_doc, {})
        if current is None:
            current = Jobs.refresh(job.id)
        if not current.dispatched:
            raise RuntimeError("Job dispatch did not complete")
        return Jobs.response(current)
    except Exception as exc:
        logger.error("Multimodal dispatch failed job=%s type=%s", job.id, type(exc).__name__)
        Jobs.fail(job.id, "dispatch_error", "Failed to publish parsing tasks; check server logs")
        raise ApiError("Unable to submit parsing job", 503, Jobs.response(MultimodalJob.get_by_id(job.id))) from exc


@DB.connection_context()
def upload(tenant_id, dataset_id, file, options):
    kb = _dataset(tenant_id, dataset_id)
    if getattr(kb, "pipeline_id", ""):
        raise ApiError("Switch dataset from Pipeline to direct parsing first", 409)
    _config(tenant_id, kb, {}, options, file.filename or "")
    errors, files = FileService.upload_document(kb, [file], tenant_id)
    if not files:
        raise ApiError("File upload failed; check file format and storage", 400)
    document = files[0][0]
    document_id = document["id"]
    if errors:
        raise ApiError("File saved but upload reported an error; retry using document_id", 400, {"document_id": document_id})
    try:
        return submit(tenant_id, dataset_id, document_id, options)
    except ApiError as exc:
        exc.data = {**(exc.data or {}), "document_id": document_id, "dataset_id": dataset_id}
        raise


@DB.connection_context()
def status(tenant_id, job_id):
    job = Jobs.get_owned(job_id, tenant_id)
    if not job:
        raise ApiError("Task not found", 404)
    _dataset(tenant_id, job.dataset_id)
    return Jobs.response(Jobs.refresh(job_id))


def test_model(tenant_id, model_ref, model_type):
    """Probe a registered OpenAI-compatible model without exposing its secret."""

    from openai import OpenAI

    if model_type not in {LLMType.CHAT.value, LLMType.VISION.value, LLMType.EMBEDDING.value}:
        raise ApiError("Connectivity testing supports chat, vision, and embedding models")
    try:
        model = resolve_model_config(tenant_id, LLMType(model_type), model_ref)
        if not model.get("api_base"):
            raise ValueError("An OpenAI-compatible endpoint is required")
        started = monotonic()
        with OpenAI(
            api_key=model.get("api_key") or "EMPTY",
            base_url=model["api_base"].rstrip("/"),
            timeout=30,
            max_retries=0,
        ) as client:
            if model_type == LLMType.EMBEDDING.value:
                response = client.embeddings.create(model=model["llm_name"], input=["connectivity test"])
                ok = bool(response.data and response.data[0].embedding)
                usage = response.usage.model_dump() if response.usage else {}
            else:
                content = "Reply with OK."
                if model_type == LLMType.VISION.value:
                    # Exercise the image-input path instead of only probing chat.
                    content = [
                        {"type": "text", "text": "Describe this image with the single word OK."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    "data:image/png;base64,"
                                    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAYElEQVR4nO3PQQ0A"
                                    "IBDAMMC/50MEj4ZkVbDtmVk/OzrgVQNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNa"
                                    "A1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgNaA1oDWgPaBXKqA31N0fbGAAAA"
                                    "AElFTkSuQmCC"
                                )
                            },
                        },
                    ]
                response = client.chat.completions.create(
                    model=model["llm_name"],
                    messages=[{"role": "user", "content": content}],
                    max_tokens=8,
                )
                ok = bool(response.choices and response.choices[0].message.content)
                usage = response.usage.model_dump() if response.usage else {}
        return {
            "ok": ok,
            "model": model["llm_name"],
            "model_type": model_type,
            "latency_ms": round((monotonic() - started) * 1000, 1),
            "usage": usage,
        }
    except LookupError as exc:
        raise ApiError("Registered model not found or unavailable", 404) from exc
    except Exception as exc:
        logger.warning("Model connectivity test failed type=%s", type(exc).__name__)
        raise ApiError(f"Model connectivity test failed: {type(exc).__name__}", 502) from exc
