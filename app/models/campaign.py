"""Voice Bot campaign models.

These models back the Voice Bot campaign wizard + dashboard UI.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Index, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.db import Base, AuditMixin


class VoiceBotCampaign(Base, AuditMixin):
    """Voice Bot campaign for lead generation."""
    
    __tablename__ = "voicebot_campaigns"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # Campaign details
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # UI config (Campaign Config step)
    campaign_type = Column(String(32), nullable=True)  # AI_CALL | AI_HUMAN_TRANSFER | FOLLOW_UP
    loan_type = Column(String(64), nullable=True)      # e.g. PERSONAL, BUSINESS...
    ai_model = Column(String(64), nullable=True)       # e.g. GPT-4o
    voice_gender = Column(String(16), nullable=True)   # MALE | FEMALE
    campaign_mode = Column(String(16), nullable=True)  # SEQUENTIAL | BULK

    # UI schedule fields (Schedule Date & Time step)
    # Store the raw config so frontend can round-trip without losing intent.
    # scheduled_start/scheduled_end are derived summary timestamps.
    schedule_config = Column(JSONB, default=dict)  # {dayMode,timeMode,startDate,endDate,startTime,endTime,selectedDays,slots}

    # Selected assistant / script from Agent Profiles
    agent_profile_id = Column(UUID(as_uuid=True), ForeignKey("agent_profiles.id"), nullable=True)
    
    # Status
    status = Column(String(20), default="DRAFT")  # DRAFT, SCHEDULED, RUNNING, PAUSED, COMPLETED, CANCELLED
    
    # Schedule
    scheduled_start = Column(DateTime, nullable=True)
    scheduled_end = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Stats
    total_contacts = Column(Integer, default=0)
    contacted = Column(Integer, default=0)
    qualified = Column(Integer, default=0)
    disqualified = Column(Integer, default=0)
    no_answer = Column(Integer, default=0)
    leads_created = Column(Integer, default=0)
    
    # Campaign script/questions
    script_config = Column(JSONB, default=dict)  # Questions, responses, qualification criteria
    
    # Source file
    source_file = Column(String(500), nullable=True)
    
    # Bolna.ai integration
    bolna_agent_id = Column(String(100), nullable=True)  # Bolna agent to use
    bolna_batch_id = Column(String(100), nullable=True)  # Bolna batch ID if using batch mode
    bolna_from_phone = Column(String(20), nullable=True)  # Caller ID
    
    # Contacts relationship
    contacts = relationship("CampaignContact", back_populates="campaign", lazy="dynamic")
    
    def __repr__(self):
        return f"<VoiceBotCampaign(id={self.id}, name={self.name})>"


class CampaignContact(Base):
    """Individual contact in a voice bot campaign."""
    
    __tablename__ = "campaign_contacts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("voicebot_campaigns.id"), nullable=False)
    
    # Contact details
    phone = Column(String(15), nullable=False)
    name = Column(String(255), nullable=True)

    # Extra lead fields used in dashboard table
    pincode = Column(String(10), nullable=True)
    location = Column(String(255), nullable=True)
    
    # Internal status (used by calling engine)
    status = Column(String(20), default="PENDING")  # PENDING, IN_PROGRESS, CONTACTED, NO_ANSWER, QUALIFIED, DISQUALIFIED, FAILED, INVALID

    # UI-friendly outcome (used for dashboard metrics/table)
    # NOT_CONNECT, ONGOING_CALL, ANSWERED_CALL, NO_ANSWER_CALL, REJECTED_CALL, CALLBACK_NEED, INCORRECT_ENTRY
    call_outcome = Column(String(32), nullable=True)
    callback_needed = Column(Boolean, nullable=False, default=False)
    
    # Call details
    call_attempts = Column(Integer, default=0)
    last_call_at = Column(DateTime, nullable=True)
    call_duration_seconds = Column(Integer, nullable=True)
    
    # Qualification result
    qualification_score = Column(Integer, nullable=True)
    responses = Column(JSONB, default=dict)  # Question-answer pairs
    
    # If lead was created
    lead_id = Column(UUID(as_uuid=True), nullable=True)
    
    # Collected data
    collected_data = Column(JSONB, default=dict)  # Any data gathered during call
    
    # Bolna.ai integration
    bolna_execution_id = Column(String(100), nullable=True)  # Bolna call execution ID
    recording_url = Column(Text, nullable=True)  # Call recording URL
    transcript = Column(Text, nullable=True)  # Call transcript
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    campaign = relationship("VoiceBotCampaign", back_populates="contacts")
    
    __table_args__ = (
        Index("ix_contact_campaign_status", "campaign_id", "status"),
        Index("ix_contact_phone", "phone"),
    )
    
    def __repr__(self):
        return f"<CampaignContact(id={self.id}, phone={self.phone})>"
