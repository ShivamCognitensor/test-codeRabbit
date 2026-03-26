from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID


@dataclass(frozen=True)
class ProviderCallInfo:
    provider: str
    provider_call_id: str
    provider_stream_id: Optional[str] = None
    to_phone: Optional[str] = None
    from_phone: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class OutboundCallRequest:
    provider: str
    to_phone: str
    from_phone: Optional[str] = None
    # optional associations for persistence / analytics
    campaign_id: Optional[UUID] = None
    campaign_contact_id: Optional[UUID] = None
    agent_profile_id: Optional[UUID] = None
    # free-form
    variables: Optional[Dict[str, Any]] = None
