"""Chatbot conversation models."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Index, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.db import Base, AuditMixin


class ChatConversation(Base, AuditMixin):
    """Chatbot conversation session."""
    
    __tablename__ = "chat_conversations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    # User
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Optional for anonymous
    session_id = Column(String(255), nullable=False, index=True)  # Browser/app session
    
    # Context
    context_type = Column(String(50), nullable=True)  # lead, general, lender_selection
    context_id = Column(UUID(as_uuid=True), nullable=True)  # e.g., lead_id
    
    # Public chat flag (for unauthenticated sessions)
    is_public = Column(Boolean, default=False, nullable=False)
    
    # Client info (for public chat security)
    client_ip = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Status
    status = Column(String(20), default="ACTIVE")  # ACTIVE, CLOSED, ESCALATED
    
    # Timestamps
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    
    # Metadata
    chat_metadata = Column(JSONB, default=dict)
    
    # Messages relationship
    messages = relationship("ChatMessage", back_populates="conversation", lazy="dynamic")
    
    __table_args__ = (
        Index("ix_chat_conv_user_status", "user_id", "status"),
        Index("ix_chat_conv_public", "is_public", "client_ip"),
    )
    
    def __repr__(self):
        return f"<ChatConversation(id={self.id}, user={self.user_id})>"


class ChatMessage(Base):
    """Individual chat message."""
    
    __tablename__ = "chat_messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("chat_conversations.id"), nullable=False)
    
    # Message details
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    
    # Intent detection (for user messages)
    detected_intent = Column(String(100), nullable=True)
    intent_confidence = Column(String(10), nullable=True)
    
    # Metadata
    message_metadata = Column(JSONB, default=dict)
    
    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    conversation = relationship("ChatConversation", back_populates="messages")
    
    __table_args__ = (
        Index("ix_chat_msg_conv_created", "conversation_id", "created_at"),
    )
    
    def __repr__(self):
        return f"<ChatMessage(id={self.id}, role={self.role})>"
