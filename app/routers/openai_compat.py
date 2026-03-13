"""OpenAI-compatible endpoints for Bolna.ai (Custom LLM server).

Bolna can be configured to call an OpenAI-compatible backend for response generation.
These endpoints intentionally mimic OpenAI's REST surface:
- GET  /v1/models
- POST /v1/chat/completions

They are *only* used for the Audio Bot / outbound calling flows.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.services.bolna.bolna_brain import BolnaBrain


router = APIRouter(prefix="/v1", tags=["bolna-llm"])


def _require_llm_secret(request: Request) -> None:
    """
    Validate an optional LLM shared secret on the incoming request and raise HTTP 401 when it is missing or incorrect.
    
    If the application setting LLM_SHARED_SECRET is not configured, this function returns without action. When the secret is configured, the function reads the header named by LLM_SECRET_HEADER_NAME (fallback "X-LLM-Secret") and compares it to the configured value.
    
    Parameters:
        request (Request): Incoming FastAPI request whose headers will be checked for the shared secret.
    
    Raises:
        HTTPException: 401 Unauthorized with detail "Invalid LLM shared secret" if the required header is missing or does not match.
    """

    if not settings.LLM_SHARED_SECRET:
        return

    header_name = settings.LLM_SECRET_HEADER_NAME or "X-LLM-Secret"
    provided = request.headers.get(header_name) or request.headers.get("X-LLM-Secret")
    if not provided or provided != settings.LLM_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid LLM shared secret")


@router.get("/models")
async def list_models(request: Request):
    """
    Return a JSON-compatible object listing the single available chat model.
    
    Returns:
        dict: An object with keys:
            - "object": the container type ("list").
            - "data": a list containing one model entry with keys:
                - "id": model identifier (from settings.OPENAI_CHAT_MODEL).
                - "object": the entry type ("model").
                - "created": creation timestamp as an integer (Unix epoch seconds).
                - "owned_by": owner identifier ("lms-finai").
    """
    _require_llm_secret(request)
    return {
        "object": "list",
        "data": [
            {
                "id": settings.OPENAI_CHAT_MODEL,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "lms-finai",
            }
        ],
    }


def _chat_completion_response(model: str, content: str) -> Dict[str, Any]:
    """
    Constructs an OpenAI-compatible chat completion response payload for a single assistant message.
    
    Returns:
        dict: Chat completion object with `id`, `object`, `created`, `model`, and a single entry in `choices` containing the assistant `message` and `finish_reason` set to `"stop"`.
    """
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


async def _sse_stream(model: str, content: str) -> AsyncGenerator[bytes, None]:
    """
    Yield Server-Sent Events (SSE) bytes that stream a chat completion in incremental chunks.
    
    Each yielded item is a bytes-encoded SSE "data: <json>\n\n" event representing a partial or final chat completion chunk; after all content chunks a final chunk with finish_reason "stop" is yielded, followed by the termination signal `data: [DONE]`.
    
    Returns:
        An asynchronous generator that yields `bytes` values formatted as SSE events.
    """

    chunk_size = 80
    for i in range(0, len(content), chunk_size):
        part = content[i : i + chunk_size]
        payload = {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": part},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    final = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle POST /v1/chat/completions: validate the request, generate a reply via BolnaBrain, and return either a single completion or a streaming SSE response.
    
    Parameters:
        request (Request): HTTP request whose JSON body must include "messages" (a non-empty list). Optional keys: "stream" (truthy to enable SSE), "model" (model id), and "user_data"/"metadata"/"context" (dict of user metadata).
        db (AsyncSession): Database session passed to BolnaBrain.
    
    Returns:
        A StreamingResponse yielding Server-Sent Events when "stream" is truthy, otherwise a dict representing a single chat completion payload.
    
    Raises:
        HTTPException: 400 if "messages" is missing or empty; 401 if the configured LLM shared secret is required and invalid.
    """
    _require_llm_secret(request)

    payload = await request.json()
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages[] required")

    stream = bool(payload.get("stream"))
    model = payload.get("model") or settings.OPENAI_CHAT_MODEL

    # Bolna may send lead metadata in different places depending on configuration.
    user_data = payload.get("user_data") or payload.get("metadata") or payload.get("context") or {}
    if not isinstance(user_data, dict):
        user_data = {}

    brain = BolnaBrain(db=db)
    content = await brain.generate_reply(messages=messages, user_data=user_data)

    if stream:
        return StreamingResponse(_sse_stream(model, content), media_type="text/event-stream")

    return _chat_completion_response(model, content)
