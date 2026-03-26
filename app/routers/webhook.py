"""External webhook aliases.

We keep the canonical webhook handler under `/internal/voicebot/...`.
Some third-party providers (or legacy deployments) might call older paths.

This router exposes a *thin alias* for the Bolna webhook without bringing back
the legacy folder structure.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.routers.internal.callback import (
    BolnaWebhookPayload,
    bolna_webhook as _internal_bolna_webhook,
    verify_bolna_webhook,
)
from shared.responses import success_response


router = APIRouter(prefix="/api/v1", tags=["webhooks"])


@router.post("/voicebot/bolna/webhook")
async def bolna_webhook_alias(
    payload: BolnaWebhookPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_bolna_webhook_secret: Optional[str] = Header(None, alias="X-Bolna-Webhook-Secret"),
):
    """Alias for Bolna webhook.

    Canonical handler: POST /internal/voicebot/bolna/webhook
    Alias path:        POST /v1/voicebot/bolna/webhook
    """
    verify_bolna_webhook(x_bolna_webhook_secret)
    return await _internal_bolna_webhook(payload=payload, request=request, db=db, verified=True)


@router.get("/voicebot/bolna/webhook/health")
async def bolna_webhook_alias_health():
    return success_response(message="Webhook endpoint healthy", data={"status": "ok"})
