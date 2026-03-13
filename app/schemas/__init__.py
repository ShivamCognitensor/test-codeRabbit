"""Pydantic schemas for FinAI Service."""
from app.schemas.chatbot import ChatMessageRequest, ChatMessageResponse, ConversationResponse
from app.schemas.voicebot import CampaignCreate, CampaignResponse, CampaignContactResponse

__all__ = [
    "ChatMessageRequest",
    "ChatMessageResponse",
    "ConversationResponse",
    "CampaignCreate",
    "CampaignResponse",
    "CampaignContactResponse",
]
