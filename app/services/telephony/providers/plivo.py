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
    """
    Normalize a phone number string to E.164 format, using +91 for 10-digit numbers when no country code is present.
    
    Parameters:
        value (str): Input phone number in any common format (may include spaces, punctuation, or a leading '+').
    
    Returns:
        str: The phone number in E.164 format (e.g., "+911234567890" or "+441234567890"), or an empty string if the input is empty or only whitespace.
    """
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
        """
        Create a PlivoProvider instance and load application settings into self.s.
        
        Sets:
            self.s: The runtime configuration returned by get_settings(), used for provider credentials and public base URLs.
        """
        self.s = get_settings()

    @property
    def is_enabled(self) -> bool:
        """
        Determine whether the Plivo provider is configured for use.
        
        Returns:
            True if both PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN are set, False otherwise.
        """
        return bool(self.s.PLIVO_AUTH_ID and self.s.PLIVO_AUTH_TOKEN)

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        """
        Initiates an outbound call through Plivo and returns information about the created call.
        
        Normalizes `to`/`from` phone numbers to E.164, constructs an answer URL (including optional agent_profile_id, campaign_id, and campaign_contact_id query parameters), posts the call request to Plivo, and returns the provider call information based on Plivo's response.
        
        Parameters:
            req (OutboundCallRequest): Outbound call request containing at least `to_phone`; may include `from_phone`, `agent_profile_id`, `campaign_id`, and `campaign_contact_id`.
        
        Returns:
            ProviderCallInfo: Contains the provider name, `provider_call_id` extracted from Plivo's response, normalized `to_phone` and `from_phone`, and the raw response metadata.
        
        Raises:
            RuntimeError: If Plivo is not configured or the Plivo API returns an error response.
            ValueError: If the effective `from_phone` is missing after normalization.
        """
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
        """
        Get the configured public HTTP base URL for telephony callbacks.
        
        Returns:
            The TELEPHONY_PUBLIC_HTTP_BASE setting with surrounding whitespace removed, or an empty string if not configured.
        """
        return (self.s.TELEPHONY_PUBLIC_HTTP_BASE or "").strip()

    def _public_ws_base(self) -> str:
        """
        Get the configured public WebSocket base URL used for telephony.
        
        Returns:
            The TELEPHONY_PUBLIC_WS_BASE setting with leading and trailing whitespace removed, or an empty string if the setting is not configured.
        """
        return (self.s.TELEPHONY_PUBLIC_WS_BASE or "").strip()

    async def answer_hook(self, request: Request) -> Response:
        """
        Generate Plivo XML response that instructs Plivo to start a bidirectional audio stream to the application's WebSocket endpoint.
        
        If a TELEPHONY_PUBLIC_WS_BASE setting is configured, it is used as the WebSocket base; otherwise the request.base_url is converted to ws:// or wss:// and used. The XML requests mulaw/8k audio and includes a status callback URL based on the TELEPHONY_PUBLIC_HTTP_BASE setting.
        
        Parameters:
            request (Request): Incoming HTTP request used to derive a fallback WebSocket base URL when a configured WS base is absent.
        
        Returns:
            Response: PlainTextResponse containing the Plivo XML with media_type "application/xml".
        """
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
