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
    """
    Expose a public v1 alias for the Bolna webhook that verifies the incoming secret and delegates processing to the internal handler.
    
    Parameters:
        payload (BolnaWebhookPayload): Parsed webhook payload from the request body.
        x_bolna_webhook_secret (Optional[str]): Value of the `X-Bolna-Webhook-Secret` header used to verify the webhook.
    
    Returns:
        The response produced by the internal Bolna webhook handler.
    
    Raises:
        HTTPException: If webhook verification fails.
    """
    verify_bolna_webhook(x_bolna_webhook_secret)
    return await _internal_bolna_webhook(payload=payload, request=request, db=db, verified=True)


@router.get("/voicebot/bolna/webhook/health")
async def bolna_webhook_alias_health():
    """
    Return a success response indicating the webhook endpoint is healthy.
    
    Returns:
        dict: Success response with "message" set to "Webhook endpoint healthy" and "data" containing {"status": "ok"}.
    """
    return success_response(message="Webhook endpoint healthy", data={"status": "ok"})
