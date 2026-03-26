from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from starlette.requests import Request

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.telephony.base import TelephonyProvider
from app.services.telephony.types import OutboundCallRequest, ProviderCallInfo

logger = get_logger(__name__)


def _as_e164_or_local(value: str) -> str:
    """Exotel accepts E.164 (recommended) and also local formats. We'll keep digits-only if not +."""
    v = (value or "").strip()
    if not v:
        return v
    if v.startswith("+"):
        return v
    digits = "".join(ch for ch in v if ch.isdigit())
    # Exotel sometimes expects leading 0 for mobiles; keep as-is if already has 0 prefix.
    return digits


class ExotelProvider(TelephonyProvider):
    name = "exotel"

    def __init__(self) -> None:
        self.s = get_settings()

    @property
    def is_enabled(self) -> bool:
        return bool(
            self.s.EXOTEL_API_KEY
            and self.s.EXOTEL_API_TOKEN
            and self.s.EXOTEL_ACCOUNT_SID
            and self.s.EXOTEL_DOMAIN
            and self.s.EXOTEL_FLOW_URL
        )

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        if not self.is_enabled:
            raise RuntimeError(
                "Exotel is not configured (EXOTEL_API_KEY/EXOTEL_API_TOKEN/EXOTEL_ACCOUNT_SID/EXOTEL_DOMAIN/EXOTEL_FLOW_URL)"
            )

        to_phone = _as_e164_or_local(req.to_phone)
        # For AI agent: call the customer first (From=customer) and then connect to the flow.
        from_phone = to_phone

        data: Dict[str, Any] = {
            "From": from_phone,
            "CallerId": self.s.EXOTEL_CALLERID,
            "Url": self.s.EXOTEL_FLOW_URL,
            "StatusCallback": (self.s.TELEPHONY_PUBLIC_HTTP_BASE or "").rstrip("/") + "/api/v1/telephony/exotel/status",
        }

        # pass campaign/contact correlation into Exotel flow as CustomField
        custom: Dict[str, Any] = {}
        if req.agent_profile_id:
            custom["agent_profile_id"] = str(req.agent_profile_id)
        if req.campaign_id:
            custom["campaign_id"] = str(req.campaign_id)
        if req.campaign_contact_id:
            custom["campaign_contact_id"] = str(req.campaign_contact_id)
        if custom:
            # Exotel supports CustomField as a string. We'll JSON-encode.
            import json
            data["CustomField"] = json.dumps(custom)

        url = f"https://{self.s.EXOTEL_DOMAIN}/v1/Accounts/{self.s.EXOTEL_ACCOUNT_SID}/Calls/connect.json"
        auth = (self.s.EXOTEL_API_KEY, self.s.EXOTEL_API_TOKEN)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=data, auth=auth)
            if resp.status_code >= 400:
                logger.error("exotel_call_failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Exotel call failed: {resp.status_code} {resp.text}")
            payload = resp.json()

        sid = (payload.get("Call") or {}).get("Sid") or ""
        return ProviderCallInfo(provider=self.name, provider_call_id=str(sid), to_phone=to_phone, from_phone=from_phone, metadata=payload)
