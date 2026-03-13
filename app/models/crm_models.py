import uuid
from sqlalchemy import Column, Integer, String, JSON, Boolean, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from app.models.enums import PincodeStatus, CallStatus


class MasterProduct(Base):
    __tablename__ = "master_products"

    id = Column(Integer, primary_key=True)
    product_name = Column(String(100), nullable=False)
    price = Column(Integer, nullable=False)
    required_docs = Column(JSON, nullable=False)


class ServiceablePincode(Base):
    __tablename__ = "serviceable_pincodes"

    pincode = Column(String(10), primary_key=True)
    status = Column(Enum(PincodeStatus), nullable=False)
    area_manager = Column(String(20))


class LeadCRM(Base):
    __tablename__ = "leads_crm"

    lead_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number = Column(String(20), index=True, nullable=False)
    call_status = Column(Enum(CallStatus), nullable=False, default=CallStatus.CALLBACK_NEEDED)
    recording_url = Column(Text)
    whatsapp_sent = Column(Boolean, default=False)

    # -------- VoiceBot (VoiceFin) relationships --------
    # These are optional and only used by VoiceFin dashboard/webhook.
    voicefin_campaign_links = relationship(
        "VoicefinCampaignLead",
        back_populates="lead",
        lazy="selectin",
    )
    voicefin_events = relationship(
        "VoicefinEvent",
        back_populates="lead",
        lazy="selectin",
    )

    # VoiceBot dashboard metadata (kept in a separate table to avoid changing the core CRM fields)
    voicefin_contact = relationship(
        "VoicefinLeadContact",
        uselist=False,
        back_populates="lead",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
