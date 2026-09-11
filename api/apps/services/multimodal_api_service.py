"""Submission orchestration for document-scoped multimodal jobs."""

import logging
from pathlib import Path

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
    parser_id = "naive" if Path(doc.name).suffix.lower() == ".pdf" else "picture"
    try:
        DocumentService.clear_chunk_num_when_rerun(document_id)
        DocumentService.update_by_id(document_id, {"parser_config": config, "parser_id": parser_id, "run": "1", "progress": 0, "progress_msg": "", "chunk_num": 0, "token_num": 0})
        task_doc = doc.to_dict()
        task_doc.update(parser_config=config, parser_id=parser_id, _multimodal_job_id=job.id)
        DocumentService.run(tenant_id, task_doc, {})
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
