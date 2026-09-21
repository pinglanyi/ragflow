#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import json
import logging
import uuid

from quart import Response

from api.apps import current_user, login_required
from api.apps.services.agentic_search_api_service import execute_agentic_search, stream_agentic_search, validate_agentic_search_request
from api.utils.api_utils import get_data_error_result, get_json_result, get_request_json
from common.constants import RetCode


@manager.route("/agentic-search", methods=["POST"])  # noqa: F821
@login_required
async def agentic_search():
    request_id = str(uuid.uuid4())
    try:
        payload = await get_request_json()
        options = validate_agentic_search_request(payload)
        data = await execute_agentic_search(tenant_id=current_user.id, options=options, request_id=request_id)
        return get_json_result(data=data)
    except (ValueError, PermissionError) as error:
        return get_data_error_result(message=str(error))
    except Exception as error:
        logging.exception("Agentic Search API failed request_id=%s", request_id)
        return get_json_result(
            code=RetCode.EXCEPTION_ERROR,
            message=repr(error),
            data={"request_id": request_id},
        )


@manager.route("/agentic-search/stream", methods=["POST"])  # noqa: F821
@login_required
async def agentic_search_stream():
    request_id = str(uuid.uuid4())
    try:
        payload = await get_request_json()
        options = validate_agentic_search_request(payload)
    except (ValueError, PermissionError) as error:
        return get_data_error_result(message=str(error))
    except Exception:
        logging.exception("Agentic Search stream request failed request_id=%s", request_id)
        return get_json_result(
            code=RetCode.EXCEPTION_ERROR,
            message="Agentic Search request failed; see server logs",
            data={"request_id": request_id},
        )

    tenant_id = current_user.id

    async def events():
        yield _sse_event("start", {"request_id": request_id})
        try:
            async for event in stream_agentic_search(tenant_id=tenant_id, options=options, request_id=request_id):
                yield _sse_event(event["event"], event["data"])
        except (ValueError, PermissionError) as error:
            logging.warning("Agentic Search stream rejected request_id=%s: %s", request_id, error)
            yield _sse_event("error", {"request_id": request_id, "message": str(error)})
        except Exception:
            logging.exception("Agentic Search stream failed request_id=%s", request_id)
            yield _sse_event("error", {"request_id": request_id, "message": "Agentic Search failed; see server logs"})

    response = Response(events(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.timeout = None
    return response


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
