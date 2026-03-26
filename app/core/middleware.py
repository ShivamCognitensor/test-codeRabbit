from __future__ import annotations

import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_401_UNAUTHORIZED

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        bind_contextvars(request_id=request_id, path=str(request.url.path), method=request.method)
        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        allowed = settings.parsed_api_keys()
        header_name = settings.api_key_header_name

        # allow health + Bolna integrations without API-key auth
        # (Bolna will call these endpoints directly)
        unauth_paths = {
            "/healthz",
            "/readyz",
            "/v1/models",
            "/v1/chat/completions",
            "/v1/voicefin/bolna/webhook",
        }
        if request.url.path in unauth_paths:
            return await call_next(request)

        provided = request.headers.get(header_name)
        if not provided or provided not in allowed:
            logger.warning("unauthorized", header_name=header_name)
            return Response(content="Unauthorized", status_code=HTTP_401_UNAUTHORIZED)

        return await call_next(request)
