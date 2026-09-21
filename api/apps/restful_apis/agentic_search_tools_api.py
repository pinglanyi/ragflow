"""Authenticated HTTP facade for the seven Mistral-style search tools."""

import logging
import uuid

from api.apps import current_user, login_required
from api.apps.services.agentic_search_tools_service import execute_tool
from api.utils.api_utils import get_data_error_result, get_json_result, get_request_json
from common.constants import RetCode


@manager.route("/agentic-search/tools/<tool_name>", methods=["POST"])  # noqa: F821
@login_required
async def agentic_search_tool(tool_name):
    """Call one search, navigation, ingestion, or deletion tool."""
    request_id = str(uuid.uuid4())
    try:
        payload = await get_request_json()
        data = await execute_tool(tool_name, payload, user_id=current_user.id)
        return get_json_result(data={**data, "request_id": request_id})
    except (ValueError, PermissionError) as error:
        return get_data_error_result(message=str(error))
    except Exception:
        logging.exception("Agentic Search tool failed tool=%s request_id=%s", tool_name, request_id)
        return get_json_result(
            code=RetCode.EXCEPTION_ERROR,
            message="Agentic Search tool failed; see server logs",
            data={"request_id": request_id},
        )
