from __future__ import annotations

import uuid

from sqlalchemy import DECIMAL, JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.base import Base


class CallAnalytics(Base):
    """Stores per-call data.

    Populated from Bolna webhooks + optional post-call LLM analysis.
    """

    __tablename__ = "call_analytics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Bolna identifiers
    execution_id = Column(String(128), nullable=False, unique=True, index=True)
    status = Column(String(64), nullable=True)

    # Our campaign mapping
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("voicefin_campaigns.id"), nullable=True, index=True)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads_crm.lead_id"), nullable=True, index=True)
    batch_id = Column(String(128), nullable=True)

    # Telephony metrics
    call_duration = Column(Integer, nullable=True)
    cost = Column(DECIMAL(10, 2), nullable=True)
    disconnect_reason = Column(String(200), nullable=True)
    recording_url = Column(Text, nullable=True)

    # Transcript + extraction
    transcript = Column(Text, nullable=True)
    extracted_data = Column(JSON, nullable=True)
    raw_payload = Column(JSON, nullable=True)

    # Post-call LLM analysis
    sentiment = Column(String(20), nullable=True)
    outcome = Column(String(40), nullable=True)
    summary = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
