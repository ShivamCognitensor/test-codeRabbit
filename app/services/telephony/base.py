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
        """
        Indicates whether the provider is enabled.
        
        Returns:
            bool: `True` if the provider is enabled, `False` otherwise.
        """
        return True

    @abstractmethod
    async def start_outbound_call(self, req: OutboundCallRequest) -> ProviderCallInfo:
        """
        Initiates an outbound call through this provider using the details in `req` and returns information about the created call.
        
        Parameters:
            req (OutboundCallRequest): Request data describing the outbound call (caller, callee, metadata, and dialing options).
        
        Returns:
            ProviderCallInfo: Provider-specific information about the initiated call (e.g., provider call ID, initial status, and any answer/recording URLs).
        """
        ...

    async def validate_webhook(self, request: Request) -> None:
        """
        Validate an incoming provider webhook request and raise if the request is invalid.
        
        Implementations should inspect the provided HTTP request (headers, body, signature, etc.) and raise an exception to indicate invalid or unauthorized webhooks. The default implementation performs no validation.
        
        Parameters:
            request (Request): The incoming Starlette HTTP request containing the webhook payload.
        """
        return None

    async def handle_status_webhook(self, request: Request) -> Dict[str, Any]:
        """
        Normalize an incoming provider status webhook into a standard payload.
        
        Parameters:
            request (Request): The incoming HTTP request from the provider webhook.
        
        Returns:
            Dict[str, Any]: A dictionary of normalized webhook fields (provider-specific keys mapped to a common schema). The default implementation returns an empty dictionary.
        """
        return {}

    async def answer_hook(self, request: Request) -> Response:
        """
        Generate an HTTP response used to answer an incoming call (for providers that return an answer URL payload, e.g., TwiML/XML).
        
        Parameters:
            request (Request): The incoming HTTP request that triggered the answer hook.
        
        Returns:
            Response: An HTTP response containing provider-specific answer content (for example, TwiML/XML or equivalent).
        
        Raises:
            NotImplementedError: If the provider does not support an answer hook.
        """
        raise NotImplementedError


class TelephonyProviderRegistry:
    def __init__(self) -> None:
        """
        Initialize an empty TelephonyProviderRegistry.
        
        Creates the internal mapping `self._providers` used to store `TelephonyProvider` instances keyed by provider name (`str`).
        """
        self._providers: Dict[str, TelephonyProvider] = {}

    def register(self, provider: TelephonyProvider) -> None:
        """
        Register a TelephonyProvider in the registry under its `name`, replacing any existing provider with the same name.
        
        Parameters:
            provider (TelephonyProvider): Provider instance to register.
        """
        self._providers[provider.name] = provider

    def get(self, name: str) -> Optional[TelephonyProvider]:
        """
        Retrieve a registered TelephonyProvider by its name.
        
        Parameters:
            name (str): The provider's registered name.
        
        Returns:
            Optional[TelephonyProvider]: The provider associated with `name`, or `None` if no provider is registered under that name.
        """
        return self._providers.get(name)

    def list(self) -> Dict[str, TelephonyProvider]:
        """
        Get a shallow copy of the registered telephony providers mapping.
        
        Returns:
            dict: A mapping from provider name (str) to the corresponding TelephonyProvider instance.
        """
        return dict(self._providers)
