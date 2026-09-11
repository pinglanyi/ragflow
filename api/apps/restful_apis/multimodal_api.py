"""Asynchronous multimodal document parsing on the standard /api/v1 service."""

import json

from quart import jsonify, request

from api.apps import login_required
from api.apps.services import multimodal_api_service as service
from api.utils.api_utils import add_tenant_id_to_kwargs
from common.misc_utils import thread_pool_exec


def _error(exc):
    value = {"code": exc.status, "message": str(exc)}
    if exc.data is not None:
        value["data"] = exc.data
    return jsonify(value), exc.status


def _id(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 32:
        raise service.ApiError(f"{field} must be a non-empty ID of at most 32 characters")
    return value


@manager.route("/multimodal/parse", methods=["POST"])  # noqa: F821
@login_required
@add_tenant_id_to_kwargs
async def parse_document(tenant_id):
    try:
        body = await request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"dataset_id", "document_id", "multimodal"}:
            raise service.ApiError("Expected dataset_id, document_id and optional multimodal object")
        dataset_id = _id(body.get("dataset_id"), "dataset_id")
        document_id = _id(body.get("document_id"), "document_id")
        options = body.get("multimodal", {})
        if not isinstance(options, dict):
            raise service.ApiError("multimodal must be an object")
        data = await thread_pool_exec(service.submit, tenant_id, dataset_id, document_id, options)
        return jsonify(code=0, data=data), 202
    except service.ApiError as exc:
        return _error(exc)


@manager.route("/multimodal/upload-and-parse", methods=["POST"])  # noqa: F821
@login_required
@add_tenant_id_to_kwargs
async def upload_document(tenant_id):
    try:
        form, files = await request.form, await request.files
        if set(form) - {"dataset_id", "multimodal"} or set(files) - {"file"}:
            raise service.ApiError("Expected dataset_id, file and optional multimodal JSON")
        dataset_id = _id(form.get("dataset_id"), "dataset_id")
        values = files.getlist("file")
        if len(values) != 1 or not values[0].filename:
            raise service.ApiError("Exactly one file is required")
        try:
            options = json.loads(form.get("multimodal", "{}"))
        except (TypeError, ValueError) as exc:
            raise service.ApiError("multimodal must be valid JSON") from exc
        if not isinstance(options, dict):
            raise service.ApiError("multimodal must be a JSON object")
        data = await thread_pool_exec(service.upload, tenant_id, dataset_id, values[0], options)
        return jsonify(code=0, data=data), 202
    except service.ApiError as exc:
        return _error(exc)


@manager.route("/multimodal/tasks/<task_id>", methods=["GET"])  # noqa: F821
@login_required
@add_tenant_id_to_kwargs
async def task_status(tenant_id, task_id):
    try:
        data = await thread_pool_exec(service.status, tenant_id, _id(task_id, "task_id"))
        return jsonify(code=0, data=data)
    except service.ApiError as exc:
        return _error(exc)
