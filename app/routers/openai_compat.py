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
    """Optional shared secret validation.

    If LLM_SHARED_SECRET is set, callers must provide it in the header defined by
    LLM_SECRET_HEADER_NAME (default: X-LLM-Secret).
    """

    if not settings.LLM_SHARED_SECRET:
        return

    header_name = settings.LLM_SECRET_HEADER_NAME or "X-LLM-Secret"
    provided = request.headers.get(header_name) or request.headers.get("X-LLM-Secret")
    if not provided or provided != settings.LLM_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid LLM shared secret")


@router.get("/models")
async def list_models(request: Request):
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
    """Naive SSE chunking for stream=true clients."""

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
