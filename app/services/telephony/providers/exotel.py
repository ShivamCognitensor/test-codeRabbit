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
    """
    Normalize a phone number for Exotel: return the input unchanged if empty or already E.164 (starts with '+'), otherwise return a digits-only local representation preserving any leading zero.
    
    Parameters:
        value (str): The phone number to normalize; leading and trailing whitespace will be removed.
    
    Returns:
        str: The normalized phone string — unchanged empty string, unchanged E.164 string starting with '+', or the input's digits (leading zeros preserved) for local format.
    """
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
        """
        Initialize the provider and load application settings.
        
        Stores the application's configuration object returned by `get_settings()` on `self.s`.
        """
        self.s = get_settings()

    @property
    def is_enabled(self) -> bool:
        """
        Check whether all required Exotel configuration settings are present.
        
        Returns:
            True if EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_ACCOUNT_SID, EXOTEL_DOMAIN, and EXOTEL_FLOW_URL are all set; False otherwise.
        """
        return bool(
            self.s.EXOTEL_API_KEY
            and self.s.EXOTEL_API_TOKEN
            and self.s.EXOTEL_ACCOUNT_SID
            and self.s.EXOTEL_DOMAIN
            and self.s.EXOTEL_FLOW_URL
        )

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        """
        Initiates an outbound call via Exotel using the provided outbound request.
        
        Builds and sends the Exotel connect request (including optional CustomField JSON for agent/campaign correlation) and returns information about the created provider call.
        
        Parameters:
            req (OutboundCallRequest): Outbound call request; uses `req.to_phone` as the destination and may include `agent_profile_id`, `campaign_id`, and `campaign_contact_id` which are forwarded to Exotel as `CustomField`.
        
        Returns:
            ProviderCallInfo: Contains `provider` (provider name), `provider_call_id` (Exotel Call Sid as a string), `to_phone`, `from_phone`, and `metadata` (the full JSON payload returned by Exotel).
        
        Raises:
            RuntimeError: If Exotel is not configured with required settings or if the Exotel API returns an error response.
        """
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
