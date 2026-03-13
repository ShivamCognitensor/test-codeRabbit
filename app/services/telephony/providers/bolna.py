from __future__ import annotations

from typing import Any, Dict, Optional

from app.clients.bolna_client import BolnaClient
from app.core.config import get_settings
from app.services.telephony.base import TelephonyProvider
from app.services.telephony.types import OutboundCallRequest, ProviderCallInfo


class BolnaProvider(TelephonyProvider):
    name = "bolna"

    def __init__(self) -> None:
        self.s = get_settings()
        self.client = BolnaClient()

    @property
    def is_enabled(self) -> bool:
        return bool(self.s.BOLNA_API_KEY)

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        if not self.is_enabled:
            raise RuntimeError("Bolna is not configured (BOLNA_API_KEY)")

        # Bolna combines telephony + agent. We treat this as a provider call id = execution_id.
        res = await self.client.make_call(
            to_phone=req.to_phone,
            agent_id=(req.variables or {}).get("bolna_agent_id"),
            from_phone=req.from_phone,
            context=req.variables or {},
        )
        execution_id = str(res.get("execution_id") or res.get("id") or "")
        return ProviderCallInfo(provider=self.name, provider_call_id=execution_id, to_phone=req.to_phone, from_phone=req.from_phone, metadata=res)
