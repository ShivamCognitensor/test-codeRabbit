"""
Import all SQLAlchemy models here so they are registered with Base.metadata.
This file is imported by alembic/env.py to ensure all models are available for migrations.
"""

# Import all model classes to register them with SQLAlchemy Base
from app.models.chat_models import ChatMessage, ChatState
from app.models.session_models import ChatSession
from app.models.crm_models import LeadCRM, MasterProduct, ServiceablePincode
from app.models.analytics_models import CallAnalytics
from app.models.voicefin_models import (
    VoicefinCampaign,
    VoicefinCampaignLead,
    VoicefinEvent,
    VoicefinLeadContact,
    VoicefinSetting,
)

__all__ = [
    "ChatMessage",
    "ChatState", 
    "ChatSession",
    "LeadCRM",
    "MasterProduct",
    "ServiceablePincode",
    "CallAnalytics",
    "VoicefinCampaign",
    "VoicefinCampaignLead",
    "VoicefinEvent",
    "VoicefinLeadContact",
    "VoicefinSetting",
]

