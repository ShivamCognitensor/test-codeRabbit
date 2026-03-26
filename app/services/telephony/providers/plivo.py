from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

import httpx
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.telephony.base import TelephonyProvider
from app.services.telephony.types import OutboundCallRequest, ProviderCallInfo

logger = get_logger(__name__)


def _as_e164(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return v
    if v.startswith("+"):
        return v
    digits = "".join(ch for ch in v if ch.isdigit())
    if len(digits) == 10:
        return "+91" + digits
    return "+" + digits


class PlivoProvider(TelephonyProvider):
    name = "plivo"

    def __init__(self) -> None:
        self.s = get_settings()

    @property
    def is_enabled(self) -> bool:
        return bool(self.s.PLIVO_AUTH_ID and self.s.PLIVO_AUTH_TOKEN)

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        if not self.is_enabled:
            raise RuntimeError("Plivo is not configured (PLIVO_AUTH_ID / PLIVO_AUTH_TOKEN)")

        to_phone = _as_e164(req.to_phone)
        from_phone = _as_e164(req.from_phone or (self.s.PLIVO_FROM_PHONE_NUMBER or ""))
        if not from_phone:
            raise ValueError("Missing from_phone (PLIVO_FROM_PHONE_NUMBER or request.from_phone)")

        answer_url = self._public_http_base().rstrip("/") + "/api/v1/telephony/plivo/answer"
        params: Dict[str, Any] = {}
        if req.agent_profile_id:
            params["agent_profile_id"] = str(req.agent_profile_id)
        if req.campaign_id:
            params["campaign_id"] = str(req.campaign_id)
        if req.campaign_contact_id:
            params["campaign_contact_id"] = str(req.campaign_contact_id)
        if params:
            import urllib.parse
            answer_url = answer_url + "?" + urllib.parse.urlencode(params)

        url = f"https://api.plivo.com/v1/Account/{self.s.PLIVO_AUTH_ID}/Call/"
        auth = (self.s.PLIVO_AUTH_ID, self.s.PLIVO_AUTH_TOKEN)

        payload = {
            "from": from_phone,
            "to": to_phone,
            "answer_url": answer_url,
            "answer_method": "GET",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, auth=auth)
            if resp.status_code >= 400:
                logger.error("plivo_call_failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Plivo call failed: {resp.status_code} {resp.text}")
            data = resp.json()

        call_uuid = (data.get("request_uuid") or data.get("call_uuid") or "")
        return ProviderCallInfo(
            provider=self.name,
            provider_call_id=str(call_uuid),
            to_phone=to_phone,
            from_phone=from_phone,
            metadata=data,
        )

    def _public_http_base(self) -> str:
        return (self.s.TELEPHONY_PUBLIC_HTTP_BASE or "").strip()

    def _public_ws_base(self) -> str:
        return (self.s.TELEPHONY_PUBLIC_WS_BASE or "").strip()

    async def answer_hook(self, request: Request) -> Response:
        """Return Plivo XML that starts bidirectional audio streaming to our WebSocket."""
        ws_base = self._public_ws_base()
        if not ws_base:
            ws_base = str(request.base_url).replace("http://", "ws://").replace("https://", "wss://").rstrip("/")
        ws_url = ws_base + "/api/v1/telephony/plivo/ws"

        # Plivo Stream element supports `bidirectional=true` and audio format selection.
        # We default to mulaw/8k to align with PSTN and OpenAI realtime g711_ulaw.
        xml = "\n".join(
            [
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
                "<Response>",
                f"  <Stream bidirectional=\"true\" contentType=\"audio/x-mulaw;rate=8000\" keepCallAlive=\"true\" statusCallbackUrl=\"{self._public_http_base().rstrip('/')}/api/v1/telephony/plivo/status\">{ws_url}</Stream>",
                "</Response>",
            ]
        )
        return PlainTextResponse(xml, media_type="application/xml")
