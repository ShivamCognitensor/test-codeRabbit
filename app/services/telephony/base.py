from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from starlette.requests import Request
from starlette.responses import Response

from app.services.telephony.types import OutboundCallRequest, ProviderCallInfo


class TelephonyProvider(ABC):
    """Outbound call + webhook integration.

    Streaming is handled by provider-specific WS/RTP protocols in `app.services.telephony.stream`.
    """

    name: str

    @property
    def is_enabled(self) -> bool:
        return True

    @abstractmethod
    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        ...

    async def validate_webhook(self, request: Request) -> None:
        """Optional: raise if invalid."""
        return None

    async def handle_status_webhook(self, request: Request) -> Dict[str, Any]:
        """Return normalized webhook payload."""
        return {}

    async def answer_hook(self, request: Request) -> Response:
        """Optional: for providers that fetch 'answer_url' (TwiML/XML)."""
        raise NotImplementedError


class TelephonyProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, TelephonyProvider] = {}

    def register(self, provider: TelephonyProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Optional[TelephonyProvider]:
        return self._providers.get(name)

    def list(self) -> Dict[str, TelephonyProvider]:
        return dict(self._providers)
