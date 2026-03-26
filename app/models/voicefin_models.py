from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"


class CampaignMode(str, enum.Enum):
    """How calls are executed.

    - BATCH: upload CSV to Bolna and schedule the batch.
    - SEQUENTIAL: server-side scheduler calls one-by-one (rate-limited) using Bolna /call.
    """

    BATCH = "BATCH"
    SEQUENTIAL = "SEQUENTIAL"


class LeadCallState(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


class VoicefinEventType(str, enum.Enum):
    # lead events
    LEAD_IMPORTED = "LEAD_IMPORTED"  # legacy
    LEADS_IMPORTED = "LEADS_IMPORTED"
    LEAD_UPDATED = "LEAD_UPDATED"

    # campaign events
    CAMPAIGN_CREATED = "CAMPAIGN_CREATED"
    CAMPAIGN_STARTED = "CAMPAIGN_STARTED"
    CAMPAIGN_PAUSED = "CAMPAIGN_PAUSED"
    CAMPAIGN_STOPPED = "CAMPAIGN_STOPPED"

    # webhooks
    WEBHOOK_RECEIVED = "WEBHOOK_RECEIVED"


class VoicefinLeadContact(Base):
    """Stores lead metadata needed by the dashboard (name/pincode) without changing leads_crm."""

    __tablename__ = "voicefin_lead_contacts"

    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads_crm.lead_id"), primary_key=True)
    name = Column(String(200))
    pincode = Column(String(10), index=True)
    created_at = Column(DateTime, server_default=func.now())

    lead = relationship("LeadCRM", back_populates="voicefin_contact", lazy="selectin")


class VoicefinSetting(Base):
    """Single-row settings for demo dashboard controls."""

    __tablename__ = "voicefin_settings"

    id = Column(Integer, primary_key=True, default=1)
    transfer_number = Column(String(30), nullable=True)
    office_hours_start = Column(String(10), nullable=True)  # e.g. "10:00"
    office_hours_end = Column(String(10), nullable=True)  # e.g. "18:00"
    timezone = Column(String(64), nullable=True)  # e.g. "Asia/Kolkata"
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class VoicefinCampaign(Base):
    __tablename__ = "voicefin_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)

    status = Column(Enum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT)
    mode = Column(Enum(CampaignMode), nullable=False, default=CampaignMode.SEQUENTIAL)

    # Optional campaign-level calling constraints
    timezone = Column(String(64), nullable=True)
    call_window_start = Column(String(10), nullable=True)  # HH:MM
    call_window_end = Column(String(10), nullable=True)  # HH:MM
    calls_per_minute = Column(Integer, nullable=True)
    batch_size = Column(Integer, nullable=True)

    # Bolna-specific overrides
    bolna_agent_id = Column(String(128), nullable=True)
    bolna_from_phone_number = Column(String(32), nullable=True)
    bolna_batch_id = Column(String(128), nullable=True)

    # Lifecycle
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    leads = relationship(
        "VoicefinCampaignLead",
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    events = relationship("VoicefinEvent", back_populates="campaign", lazy="selectin")


class VoicefinCampaignLead(Base):
    __tablename__ = "voicefin_campaign_leads"

    __table_args__ = (UniqueConstraint("campaign_id", "lead_id", name="uq_voicefin_campaign_lead"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("voicefin_campaigns.id"), index=True, nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads_crm.lead_id"), index=True, nullable=False)
    sequence = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)

    # Call execution tracking
    call_state = Column(Enum(LeadCallState), nullable=False, default=LeadCallState.PENDING)
    execution_id = Column(String(128), nullable=True, index=True)
    attempts = Column(Integer, nullable=True, default=0)
    last_called_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    campaign = relationship("VoicefinCampaign", back_populates="leads", lazy="selectin")
    lead = relationship("LeadCRM", back_populates="voicefin_campaign_links", lazy="selectin")


class VoicefinEvent(Base):
    __tablename__ = "voicefin_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(Enum(VoicefinEventType), nullable=False)
    message = Column(Text, nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("voicefin_campaigns.id"), nullable=True)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads_crm.lead_id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)

    campaign = relationship("VoicefinCampaign", back_populates="events", lazy="selectin")
    lead = relationship("LeadCRM", back_populates="voicefin_events", lazy="selectin")
