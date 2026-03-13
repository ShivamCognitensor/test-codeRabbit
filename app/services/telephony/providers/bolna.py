from __future__ import annotations

from typing import Any, Dict, Optional

from app.clients.bolna_client import BolnaClient
from app.core.config import get_settings
from app.services.telephony.base import TelephonyProvider
from app.services.telephony.types import OutboundCallRequest, ProviderCallInfo


class BolnaProvider(TelephonyProvider):
    name = "bolna"

    def __init__(self) -> None:
        """
        Initialize the provider instance.
        
        Attributes:
            s: Application settings returned by get_settings().
            client: Initialized BolnaClient used to interact with the Bolna API.
        """
        self.s = get_settings()
        self.client = BolnaClient()

    @property
    def is_enabled(self) -> bool:
        """
        Indicates whether the Bolna provider is configured.
        
        Returns:
            `true` if the `BOLNA_API_KEY` setting is present and non-empty, `false` otherwise.
        """
        return bool(self.s.BOLNA_API_KEY)

    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        """
        Start an outbound call via Bolna and return provider call information.
        
        Parameters:
            req (OutboundCallRequest): Request containing `to_phone`, `from_phone`, and optional `variables`.
                If `variables` contains `bolna_agent_id`, it will be passed to Bolna as the agent identifier.
        
        Returns:
            ProviderCallInfo: Object with `provider` set to this provider's name, `provider_call_id` set to Bolna's execution identifier (uses `execution_id` or `id`, cast to string), `to_phone`/`from_phone` copied from the request, and `metadata` containing the raw Bolna response.
        
        Raises:
            RuntimeError: If the provider is not configured (missing BOLNA_API_KEY).
        """
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
