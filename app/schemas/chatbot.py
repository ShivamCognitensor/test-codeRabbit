"""Pydantic schemas for chatbot."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# class ChatMessageRequest(BaseModel):
#     """Schema for sending a chat message (authenticated)."""
    
#     session_id: str = Field(..., description="Browser/app session ID")
#     message: str = Field(..., description="User message", min_length=1, max_length=2000)
#     context_type: Optional[str] = None
#     context_id: Optional[UUID] = None

class ChatMessageRequest(BaseModel):
    """Schema for sending a chat message (authenticated or public).

    Notes:
    - `session_id` is optional. If omitted, the backend generates a new session id and returns it.
    - `is_login` controls which flow is used:
        - True  -> authenticated chat (requires Authorization / x-user-id headers)
        - False -> public chat (rate limited)
      If omitted, the backend infers it based on whether the request is authenticated.
    """

    session_id: Optional[str] = Field(
        default=None,
        description="Chat session ID. If omitted, backend will generate.",
        min_length=10,
        max_length=64,
    )
    is_login: Optional[bool] = Field(
        default=None,
        description="True for authenticated chat, False for public chat. If omitted, inferred.",
    )
    message: str = Field(..., description="User message", min_length=1, max_length=2000)
    context_type: Optional[str] = None
    context_id: Optional[UUID] = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: Optional[str]) -> Optional[str]:
        """Ensure session_id is safe if provided."""
        if v is None:
            return v
        import re
        if not re.match(r"^[a-zA-Z0-9\-_]+$", v):
            raise ValueError("session_id must be alphanumeric (with hyphens/underscores)")
        return v


class PublicChatRequest(BaseModel):
    """
    Schema for public (unauthenticated) chat message.
    More restrictive validation for security.
    """
    
    session_id: str = Field(..., description="Session ID", min_length=10, max_length=64)
    message: str = Field(..., description="User message", min_length=1, max_length=500)
    
    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v):
        """Ensure session_id is alphanumeric with hyphens only."""
        import re
        if not re.match(r'^[a-zA-Z0-9\-_]+$', v):
            raise ValueError('session_id must be alphanumeric (with hyphens/underscores)')
        return v
    
    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        """Basic input sanitization."""
        # Strip excessive whitespace
        v = ' '.join(v.split())
        # Remove any control characters
        v = ''.join(char for char in v if char.isprintable() or char in '\n\t')
        return v


class PublicChatResponse(BaseModel):
    """Response for public chat with usage limits."""
    
    conversation_id: str
    response: str
    intent: Optional[str] = None
    usage: dict = Field(
        default_factory=dict,
        description="Session usage info (messages_used, messages_remaining)"
    )


class ChatMessageResponse(BaseModel):
    """Schema for chat message response."""
    
    id: UUID
    role: str
    content: str
    detected_intent: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    """Schema for conversation with messages."""
    
    id: UUID
    session_id: str
    user_id: Optional[UUID] = None
    context_type: Optional[str] = None
    context_id: Optional[UUID] = None
    status: str
    started_at: datetime
    messages: List[ChatMessageResponse]
    
    class Config:
        from_attributes = True


class FAQResponse(BaseModel):
    """Schema for FAQ response."""
    
    question: str
    answer: str
    category: str
    relevance_score: float


class LenderRecommendation(BaseModel):
    """Schema for lender recommendation from chatbot."""
    
    lender_name: str
    product_name: str
    reason: str
    match_score: float

class LenderAdviceRequest(BaseModel):
    """Request body for /lender-advice."""

    lead_id: UUID = Field(..., description="Lead ID")
    question: str = Field(..., description="User question", min_length=5, max_length=500)