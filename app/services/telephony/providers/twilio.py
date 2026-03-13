from __future__ import annotations

import base64
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
    # assume India if 10 digits
    digits = "".join(ch for ch in v if ch.isdigit())
    if len(digits) == 10:
        return "+91" + digits
    return "+" + digits


class TwilioProvider(TelephonyProvider):
    name = "twilio"

    def __init__(self) -> None:
        self.s = get_settings()

    @property
    def is_enabled(self) -> bool:
        return bool(self.s.TWILIO_ACCOUNT_SID and self.s.TWILIO_AUTH_TOKEN)

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        if not self.is_enabled:
            raise RuntimeError("Twilio is not configured (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)")

        to_phone = _as_e164(req.to_phone)
        from_phone = _as_e164(req.from_phone or (self.s.TWILIO_FROM_PHONE_NUMBER or ""))
        if not from_phone:
            raise ValueError("Missing from_phone (TWILIO_FROM_PHONE_NUMBER or request.from_phone)")

        # Twilio will fetch TwiML from our answer URL.
        answer_url = self._public_http_base().rstrip("/") + "/api/v1/telephony/twilio/voice"

        params: Dict[str, Any] = {}
        if req.agent_profile_id:
            params["agent_profile_id"] = str(req.agent_profile_id)
        if req.campaign_id:
            params["campaign_id"] = str(req.campaign_id)
        if req.campaign_contact_id:
            params["campaign_contact_id"] = str(req.campaign_contact_id)
        # querystring to help correlate
        if params:
            import urllib.parse
            answer_url = answer_url + "?" + urllib.parse.urlencode(params)

        data = {
            "To": to_phone,
            "From": from_phone,
            "Url": answer_url,
            # status callbacks (optional)
            "StatusCallback": self._public_http_base().rstrip("/") + "/api/v1/telephony/twilio/status",
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
            "StatusCallbackMethod": "POST",
        }

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.s.TWILIO_ACCOUNT_SID}/Calls.json"
        auth = (self.s.TWILIO_ACCOUNT_SID, self.s.TWILIO_AUTH_TOKEN)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=data, auth=auth)
            if resp.status_code >= 400:
                logger.error("twilio_call_failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Twilio call failed: {resp.status_code} {resp.text}")
            payload = resp.json()

        return ProviderCallInfo(
            provider=self.name,
            provider_call_id=str(payload.get("sid") or payload.get("CallSid") or ""),
            to_phone=to_phone,
            from_phone=from_phone,
            metadata=payload,
        )

    def _public_http_base(self) -> str:
        return (self.s.TELEPHONY_PUBLIC_HTTP_BASE or "").strip()

    def _public_ws_base(self) -> str:
        return (self.s.TELEPHONY_PUBLIC_WS_BASE or "").strip()

    async def answer_hook(self, request: Request) -> Response:
        """Return TwiML that connects to our WS media gateway."""
        # Build WS URL
        ws_base = self._public_ws_base()
        if not ws_base:
            # derive from inbound request; may be http(s)
            ws_base = str(request.base_url).replace("http://", "ws://").replace("https://", "wss://").rstrip("/")
        ws_url = ws_base + "/api/v1/telephony/twilio/ws"

        # pass through correlation params (Twilio <Parameter/> are safer than querystring,
        # but we keep both; querystring helps when testing from browser.)
        agent_profile_id = request.query_params.get("agent_profile_id")
        campaign_id = request.query_params.get("campaign_id")
        campaign_contact_id = request.query_params.get("campaign_contact_id")

        # TwiML: <Connect><Stream url="wss://..."><Parameter name="..." value="..."/></Stream></Connect>
        parts = [
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<Response>",
            "  <Connect>",
            f"    <Stream url=\"{ws_url}\">",
        ]
        if agent_profile_id:
            parts.append(f"      <Parameter name=\"agent_profile_id\" value=\"{agent_profile_id}\"/>")
        if campaign_id:
            parts.append(f"      <Parameter name=\"campaign_id\" value=\"{campaign_id}\"/>")
        if campaign_contact_id:
            parts.append(f"      <Parameter name=\"campaign_contact_id\" value=\"{campaign_contact_id}\"/>")
        parts += [
            "    </Stream>",
            "  </Connect>",
            "</Response>",
        ]
        xml = "\n".join(parts)
        return PlainTextResponse(xml, media_type="application/xml")
