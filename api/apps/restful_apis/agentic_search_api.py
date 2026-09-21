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

import logging
import uuid

from api.apps import current_user, login_required
from api.apps.services.agentic_search_api_service import execute_agentic_search, validate_agentic_search_request
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
