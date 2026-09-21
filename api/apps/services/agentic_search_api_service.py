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
import time
import uuid
from copy import deepcopy
from types import SimpleNamespace


_ALLOWED_FIELDS = {
    "query",
    "chat_id",
    "session_id",
    "dataset_ids",
    "model",
    "reasoning",
    "top_n",
    "similarity_threshold",
}

_STATELESS_PROMPT_CONFIG = {
    "system": (
        "You are an intelligent assistant. Answer the question based on the supplied knowledge base.\n"
        "Answers need to consider the available evidence and cite relevant sources.\n"
        "Here is the knowledge base:\n{knowledge}\nThe above is the knowledge base."
    ),
    "prologue": "",
    "parameters": [{"key": "knowledge", "optional": False}],
    "empty_response": "Sorry! No relevant content was found in the knowledge base!",
    "quote": True,
    "tts": False,
    "refine_multiturn": False,
}


def validate_agentic_search_request(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")

    unknown = sorted(set(payload) - _ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required")
    options = dict(payload)
    options["query"] = query.strip()
    options["reasoning"] = payload.get("reasoning", 3)
    if not isinstance(options["reasoning"], int) or isinstance(options["reasoning"], bool) or not 1 <= options["reasoning"] <= 4:
        raise ValueError("reasoning must be an integer from 1 to 4")

    dataset_ids = payload.get("dataset_ids")
    if dataset_ids is not None:
        if not isinstance(dataset_ids, list) or any(not isinstance(item, str) for item in dataset_ids):
            raise ValueError("dataset_ids must be a list of strings")
        options["dataset_ids"] = list(dict.fromkeys(item.strip() for item in dataset_ids if item.strip()))

    if "top_n" in payload:
        if not isinstance(payload["top_n"], int) or isinstance(payload["top_n"], bool) or payload["top_n"] <= 0:
            raise ValueError("top_n must be a positive integer")
    if "similarity_threshold" in payload:
        threshold = payload["similarity_threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValueError("similarity_threshold must be between 0 and 1")

    for name in ("session_id", "model"):
        if name in options and options[name] is not None:
            if not isinstance(options[name], str):
                raise ValueError(f"{name} must be a string")
            options[name] = options[name].strip()

    chat_id = payload.get("chat_id")
    if chat_id is not None and not isinstance(chat_id, str):
        raise ValueError("chat_id must be a string")
    if isinstance(chat_id, str) and chat_id.strip():
        options["chat_id"] = chat_id.strip()
    else:
        options.pop("chat_id", None)

    if not options.get("chat_id") and not options.get("dataset_ids"):
        raise ValueError("chat_id or a non-empty dataset_ids list is required")
    if not options.get("chat_id") and options.get("session_id"):
        raise ValueError("session_id requires chat_id")
    return options


def build_stateless_dialog(*, tenant_id: str, dataset_ids: list[str], model: str, options: dict):
    return SimpleNamespace(
        tenant_id=tenant_id,
        llm_id=model,
        tenant_llm_id=None,
        llm_setting={},
        prompt_config=deepcopy(_STATELESS_PROMPT_CONFIG),
        kb_ids=list(dataset_ids),
        top_n=options.get("top_n", 6),
        top_k=1024,
        rerank_id="",
        similarity_threshold=options.get("similarity_threshold", 0.1),
        vector_similarity_weight=0.3,
        meta_data_filter=None,
    )


def apply_dialog_overrides(dialog, options: dict):
    copied = deepcopy(dialog)
    if "dataset_ids" in options:
        copied.kb_ids = list(options["dataset_ids"])
    if options.get("model"):
        copied.llm_id = options["model"]
        copied.tenant_llm_id = None
    if "top_n" in options:
        copied.top_n = options["top_n"]
    if "similarity_threshold" in options:
        copied.similarity_threshold = options["similarity_threshold"]
    return copied


def _normalize_reference(chunk: dict) -> dict:
    return {
        "chunk_id": chunk.get("id") or chunk.get("chunk_id"),
        "dataset_id": chunk.get("dataset_id") or chunk.get("kb_id"),
        "document_id": chunk.get("document_id") or chunk.get("doc_id"),
        "document_name": chunk.get("document_name") or chunk.get("docnm_kwd"),
        "content": chunk.get("content") or chunk.get("content_with_weight"),
        "similarity": chunk.get("similarity"),
        "positions": chunk.get("positions") or [],
        "image_id": chunk.get("image_id") or "",
        "url": chunk.get("url"),
    }


def normalize_agentic_search_result(
    result: dict,
    *,
    request_id: str,
    chat_id: str,
    model: str,
    reasoning: int,
    elapsed_ms: int,
) -> dict:
    reference = result.get("reference") if isinstance(result, dict) else {}
    chunks = reference.get("chunks", []) if isinstance(reference, dict) else []
    references = [_normalize_reference(chunk) for chunk in chunks if isinstance(chunk, dict)]
    return {
        "request_id": request_id,
        "chat_id": chat_id,
        "session_id": result.get("session_id"),
        "answer": result.get("answer") or "",
        "references": references,
        "reference_count": len(references),
        "model": model,
        "reasoning": reasoning,
        "elapsed_ms": elapsed_ms,
    }


async def execute_agentic_search(*, tenant_id: str, options: dict, request_id: str | None = None) -> dict:
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.conversation_service import ConversationService, structure_answer
    from api.db.services.dialog_service import DialogService, rag_agent
    from api.db.services.knowledgebase_service import KnowledgebaseService, validate_dataset_embedding_models
    from common.constants import LLMType, StatusEnum
    from common.misc_utils import get_uuid, thread_pool_exec

    started = time.monotonic()
    request_id = request_id or str(uuid.uuid4())
    chat_id = options["chat_id"]
    logging.info("agentic_search request_id=%s chat_id=%s start", request_id, chat_id)

    dialogs = await thread_pool_exec(DialogService.query, id=chat_id, tenant_id=tenant_id, status=StatusEnum.VALID.value)
    if not dialogs:
        raise PermissionError("Chat not found or not authorized")
    source_dialog = dialogs[0]

    dataset_ids = options.get("dataset_ids")
    if dataset_ids is not None:
        knowledgebases = []
        for dataset_id in dataset_ids:
            accessible = await thread_pool_exec(KnowledgebaseService.accessible, kb_id=dataset_id, user_id=tenant_id)
            matches = await thread_pool_exec(KnowledgebaseService.query, id=dataset_id) if accessible else []
            if not matches:
                raise PermissionError(f"Dataset {dataset_id} not found or not authorized")
            if matches[0].chunk_num == 0:
                raise ValueError(f"Dataset {dataset_id} has no parsed chunks")
            knowledgebases.append(matches[0])
        embedding_error = validate_dataset_embedding_models(knowledgebases)
        if embedding_error:
            raise ValueError(embedding_error)

    model = options.get("model") or source_dialog.llm_id
    if not model:
        raise ValueError("No chat model configured")
    await thread_pool_exec(resolve_model_config, tenant_id=tenant_id, model_type=LLMType.CHAT, model_ref=model)
    dialog = apply_dialog_overrides(source_dialog, options)

    session_id = options.get("session_id") or ""
    if session_id:
        found, conversation = await thread_pool_exec(ConversationService.get_by_id, session_id)
        if not found or conversation.dialog_id != chat_id or (conversation.user_id and conversation.user_id != tenant_id):
            raise PermissionError("Session not found or not authorized")
    else:
        session_id = get_uuid()
        conversation_data = {
            "id": session_id,
            "dialog_id": chat_id,
            "name": "Agentic Search",
            "message": [{"role": "assistant", "content": dialog.prompt_config.get("prologue", "")}],
            "user_id": tenant_id,
            "reference": [],
        }
        await thread_pool_exec(ConversationService.save, **conversation_data)
        found, conversation = await thread_pool_exec(ConversationService.get_by_id, session_id)
        if not found:
            raise RuntimeError("Failed to create Agentic Search session")

    message_id = get_uuid()
    user_message = {"role": "user", "content": options["query"], "id": message_id}
    if not conversation.message:
        conversation.message = []
    conversation.message.append(user_message)
    messages = []
    for message in conversation.message:
        if message.get("role") == "system":
            continue
        if message.get("role") == "assistant" and not messages:
            continue
        messages.append(message)

    if not conversation.reference:
        conversation.reference = []
    conversation.reference = [item for item in conversation.reference if item]
    conversation.reference.append({"chunks": [], "doc_aggs": []})

    final = None
    async for answer in rag_agent(dialog, messages, False, session_id=session_id, reasoning=options["reasoning"]):
        final = structure_answer(conversation, answer, message_id, session_id)
        break
    if not final or not final.get("answer"):
        raise RuntimeError("Agentic Search returned an empty answer")

    await thread_pool_exec(ConversationService.update_by_id, conversation.id, conversation.to_dict())
    elapsed_ms = round((time.monotonic() - started) * 1000)
    logging.info(
        "agentic_search request_id=%s chat_id=%s session_id=%s elapsed_ms=%s references=%s success",
        request_id,
        chat_id,
        session_id,
        elapsed_ms,
        len((final.get("reference") or {}).get("chunks", [])),
    )
    return normalize_agentic_search_result(
        final,
        request_id=request_id,
        chat_id=chat_id,
        model=model,
        reasoning=options["reasoning"],
        elapsed_ms=elapsed_ms,
    )
