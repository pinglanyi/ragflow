"""Authenticated document-level retrieval alongside the chunk retrieval API."""

import logging
import uuid

from api.apps import current_user, login_required
from api.apps.services.agentic_search_document_service import retrieve_documents_by_name
from api.utils.api_utils import get_data_error_result, get_json_result, get_request_json
from common.constants import RetCode


@manager.route("/retrieval-doc-name", methods=["POST"])  # noqa: F821
@login_required
async def retrieval_doc_name():
    """Find candidate files by name or document-level metadata description."""
    request_id = str(uuid.uuid4())
    try:
        payload = await get_request_json()
        data = await retrieve_documents_by_name(payload, user_id=current_user.id)
        return get_json_result(data={**data, "request_id": request_id})
    except (ValueError, PermissionError) as error:
        return get_data_error_result(message=str(error))
    except Exception:
        logging.exception("Document retrieval failed request_id=%s", request_id)
        return get_json_result(
            code=RetCode.EXCEPTION_ERROR,
            message="Document retrieval failed; see server logs",
            data={"request_id": request_id},
        )
