"""Durable state for screenshot-multimodal document jobs."""

import logging
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from api.db.db_models import DB, Document, MultimodalJob, Task

logger = logging.getLogger(__name__)

TERMINAL = ("complete", "failed", "cancelled")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".tif", ".tiff", ".webp"}


def build_config(kb_config, doc_config, overrides, filename):
    if not isinstance(overrides, dict):
        raise TypeError("multimodal must be an object")
    suffix = Path(filename).suffix.lower()
    supported = IMAGE_SUFFIXES | {
        ".pdf", ".doc", ".docx", ".rtf", ".wps", ".odt", ".ppt", ".pptx", ".odp",
        ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".csv", ".txt", ".md", ".rst",
        ".html", ".xml", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".sql",
        ".py", ".js", ".ts", ".java", ".go", ".c", ".cpp", ".h", ".css", ".tex",
        ".eml", ".msg", ".epub",
    }
    if suffix not in supported:
        raise ValueError("This file type cannot be rendered for multimodal parsing")
    allowed = {"enabled", "mode", "model", "prompt", "router_prompt", "router_max_tokens", "max_tokens", "enable_thinking", "model_revision", "reuse"}
    if set(overrides) - allowed:
        raise ValueError("Unknown multimodal fields: " + ", ".join(sorted(set(overrides) - allowed)))
    cfg = deepcopy(kb_config or {})
    cfg.update(deepcopy(doc_config or {}))
    options = {"enabled": True, "mode": "full", "prompt": "", "router_prompt": "", "router_max_tokens": 64, "max_tokens": 8192, "enable_thinking": False, "model_revision": "", "reuse": True}
    for source in (kb_config or {}, doc_config or {}):
        options.update(source.get("multimodal") or (source.get("ext") or {}).get("multimodal") or {})
    options.update(overrides)
    mode = str(options.get("mode") or ("full" if options.get("enabled") else "off")).lower()
    if mode not in {"smart", "full"}:
        raise ValueError("This endpoint requires multimodal mode smart or full")
    options["mode"] = mode
    options["enabled"] = True
    for field in ("reuse", "enable_thinking"):
        if type(options[field]) is not bool:
            raise ValueError(f"{field} must be a boolean")
    for field in ("model", "prompt", "router_prompt", "model_revision"):
        if not isinstance(options.get(field), str) or (field == "model" and not options[field].strip()):
            raise ValueError(f"{field} must be a string; model must not be empty")
    if type(options["max_tokens"]) is not int or not 256 <= options["max_tokens"] <= 65536:
        raise ValueError("max_tokens must be an integer between 256 and 65536")
    if type(options["router_max_tokens"]) is not int or not 1 <= options["router_max_tokens"] <= 1024:
        raise ValueError("router_max_tokens must be an integer between 1 and 1024")
    cfg.update(multimodal=options, layout_recognize="DeepDOC", enable_children=False, parent_child={"use_parent_child": False}, children_delimiter="")
    # Do not leave contradictory extension values that downstream merging could restore.
    ext = cfg.get("ext") or {}
    cfg["ext"] = {k: v for k, v in ext.items() if k not in ("multimodal", "enable_children", "parent_child", "children_delimiter", "layout_recognize")}
    return cfg


def _now():
    return datetime.now(UTC).isoformat()


def _signal_cancel(task_ids):
    # The durable write fence below remains authoritative when Redis is unavailable.
    try:
        from rag.utils.redis_conn import REDIS_CONN

        for task_id in task_ids:
            REDIS_CONN.set(f"{task_id}-cancel", "x")
    except Exception:  # noqa: BLE001 -- best effort; the database write fence is authoritative
        logger.warning("Could not publish multimodal child cancellation signals")


@DB.connection_context()
def guarded_insert(task_id, chunks, index_name, dataset_id, insert):
    """Fence stale custom workers against native/custom replacement and index deletion."""
    if not chunks:
        return insert(chunks, index_name, dataset_id)
    doc_id = chunks[0].get("doc_id")
    job = next((j for j in MultimodalJob.select().where(MultimodalJob.document_id == doc_id) if task_id in j.task_ids), None)
    if job is None:
        return insert(chunks, index_name, dataset_id)
    with DB.lock("mm-write-" + job.document_id, -1):
        current = MultimodalJob.get_by_id(job.id)
        child = Task.get_or_none(Task.id == task_id)
        if current.status in TERMINAL or child is None or child.progress < 0:
            raise RuntimeError("Multimodal task is no longer active; stale index write rejected")
        return insert(chunks, index_name, dataset_id)


class MultimodalJobService:
    IMAGE_SUFFIXES = IMAGE_SUFFIXES
    @staticmethod
    def create(tenant_id, dataset_id, document_id, config):
        now = _now()
        return MultimodalJob.create(id=uuid4().hex, tenant_id=tenant_id, dataset_id=dataset_id, document_id=document_id, active_document_id=document_id, config=config, created_at=now, updated_at=now)

    @staticmethod
    def get_owned(job_id, tenant_id):
        return MultimodalJob.get_or_none((MultimodalJob.id == job_id) & (MultimodalJob.tenant_id == tenant_id))

    @staticmethod
    def _update(job_id, **values):
        values["updated_at"] = _now()
        if values.get("status") in TERMINAL:
            values["active_document_id"] = None
        with DB.atomic():
            changed = MultimodalJob.update(**values).where((MultimodalJob.id == job_id) & ~MultimodalJob.status.in_(TERMINAL)).execute()
            if changed and values.get("status") == "failed":
                job = MultimodalJob.get_by_id(job_id)
                Task.update(progress=-1).where(Task.id.in_(job.task_ids) & (Task.progress < 1)).execute()
                other_active = Task.select().where((Task.doc_id == job.document_id) & ~Task.id.in_(job.task_ids) & (Task.progress >= 0) & (Task.progress < 1)).exists()
                if not other_active:
                    Document.update(run="4", progress=-1).where((Document.id == job.document_id) & (Document.run != "2")).execute()
                _signal_cancel(job.task_ids)

    @classmethod
    def bind_tasks(cls, job_id, task_ids):
        if not task_ids:
            raise ValueError("No parse tasks were generated; check the PDF and page ranges")
        cls._update(job_id, task_ids=list(task_ids))

    @classmethod
    def mark_dispatched(cls, job_id):
        cls._update(job_id, dispatched=True)
        return cls.refresh(job_id)

    @classmethod
    def fail(cls, job_id, code, message):
        with DB.lock("mmjob-" + job_id, -1):
            job = MultimodalJob.get_by_id(job_id)
            if job.status not in TERMINAL:
                cls._update(job_id, status="failed", message=message, error={"code": code, "message": message})

    @classmethod
    def record_metrics(cls, job_id, *, usage, elapsed_seconds, routed_chunks, multimodal_chunks):
        with DB.lock("mmjob-metrics-" + job_id, -1):
            job = MultimodalJob.get_by_id(job_id)
            metrics = dict(job.metrics or {})
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                metrics[key] = int(metrics.get(key, 0)) + int(usage.get(key, 0))
            metrics["routed_chunks"] = int(metrics.get("routed_chunks", 0)) + int(routed_chunks)
            metrics["multimodal_chunks"] = int(metrics.get("multimodal_chunks", 0)) + int(multimodal_chunks)
            metrics["processing_seconds"] = round(
                max(float(metrics.get("processing_seconds", 0)), float(elapsed_seconds)), 3
            )
            MultimodalJob.update(metrics=metrics, updated_at=_now()).where(
                MultimodalJob.id == job_id
            ).execute()

    @classmethod
    def refresh(cls, job_id):
        with DB.lock("mmjob-" + job_id, -1):
            job = MultimodalJob.get_by_id(job_id)
            if job.status in TERMINAL:
                return job
            doc = Document.get_or_none(Document.id == job.document_id)
            if not doc or str(doc.run) == "2":
                cls._update(job_id, status="cancelled", message="Document deleted or parsing cancelled")
            elif not job.dispatched:
                # Crash before dispatch commit is not a successful submission. Never guess success.
                age = (datetime.now(UTC) - datetime.fromisoformat(job.created_at)).total_seconds()
                if age > 600:
                    cls._update(job_id, status="failed", message="Dispatch interrupted; submit again after checking active workers", error={"code": "dispatch_interrupted"})
            else:
                rows = list(Task.select().where(Task.id.in_(job.task_ids)).dicts())
                if not job.task_ids or len(rows) != len(job.task_ids) or any(r["doc_id"] != job.document_id for r in rows):
                    cls._update(job_id, status="cancelled", message="Original parse tasks were removed or replaced")
                elif any(r["progress"] < 0 for r in rows):
                    failed_ids = [r["id"] for r in rows if r["progress"] < 0]
                    cls._update(job_id, status="failed", message="Parsing failed; inspect document progress logs and archive", error={"code": "parse_failed", "internal_task_ids": failed_ids})
                else:
                    progress = sum(max(0, min(1, r["progress"])) for r in rows) / len(rows)
                    chunk_count = len({c for r in rows for c in (r.get("chunk_ids") or "").split()})
                    status = "running" if any(r["progress"] > 0 or r.get("retry_count", 0) for r in rows) else "queued"
                    message = "Parsing and indexing" if status == "running" else "Queued"
                    error = {}
                    if all(r["progress"] >= 1 for r in rows):
                        status = "complete" if chunk_count else "failed"
                        message = "Multimodal parsing, embedding and indexing complete" if chunk_count else "No chunks produced"
                        if not chunk_count:
                            error = {"code": "empty_output", "message": message}
                    cls._update(job_id, status=status, progress=progress, chunk_count=chunk_count, message=message, error=error)
            return MultimodalJob.get_by_id(job_id)

    @classmethod
    def refresh_document(cls, doc_id):
        for job in MultimodalJob.select().where((MultimodalJob.document_id == doc_id) & ~MultimodalJob.status.in_(TERMINAL)):
            cls.refresh(job.id)

    @classmethod
    def before_delete(cls, task_ids):
        task_ids = set(task_ids)
        if not task_ids:
            return
        doc_ids = [t.doc_id for t in Task.select(Task.doc_id).where(Task.id.in_(task_ids))]
        for job in MultimodalJob.select().where((MultimodalJob.document_id.in_(doc_ids)) & ~MultimodalJob.status.in_(TERMINAL)):
            if not task_ids.intersection(job.task_ids):
                continue
            current = cls.refresh(job.id)
            if current.status not in TERMINAL:
                MultimodalJob.update(status="cancelled", active_document_id=None, updated_at=_now(), message="Original parse tasks were removed or replaced").where(
                    (MultimodalJob.id == job.id) & ~MultimodalJob.status.in_(TERMINAL)
                ).execute()
                _signal_cancel(job.task_ids)

    @classmethod
    def prepare_task(cls, task):
        for job in MultimodalJob.select().where(MultimodalJob.document_id == task["doc_id"]):
            if task["id"] in job.task_ids:
                if job.status in TERMINAL:
                    return None
                task["parser_config"] = deepcopy(job.config)
                task["kb_parser_config"] = deepcopy(job.config)
                task["_multimodal_job_id"] = job.id
                task["parser_id"] = (
                    (job.config.get("ext") or {}).get("_multimodal_base_parser_id")
                    or task.get("parser_id")
                    or ("picture" if Path(task.get("name") or "").suffix.lower() in IMAGE_SUFFIXES else "naive")
                )
                break
        return task

    @staticmethod
    def response(job):
        result = {key: getattr(job, key) for key in ("id", "dataset_id", "document_id", "status", "progress", "message", "created_at", "updated_at", "chunk_count")}
        result["task_id"] = result.pop("id")
        result["error"] = job.error or None
        result["metrics"] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "routed_chunks": 0,
            "multimodal_chunks": 0,
            "processing_seconds": 0,
            **(job.metrics or {}),
        }
        started = datetime.fromisoformat(job.created_at)
        finished = datetime.fromisoformat(job.updated_at) if job.status in TERMINAL else datetime.now(UTC)
        result["elapsed_seconds"] = round(max(0, (finished - started).total_seconds()), 3)
        result["status_url"] = f"/api/v1/multimodal/tasks/{job.id}"
        if job.status == "complete":
            result["result_url"] = f"/api/v1/datasets/{job.dataset_id}/documents/{job.document_id}/chunks"
        return result
