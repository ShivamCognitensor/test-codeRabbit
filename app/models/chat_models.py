"""Legacy chat models.

Option A migration: the *new* chat schema is the source of truth.
- The canonical chat messages table/model is `app.models.conversation.ChatMessage`.
- Legacy code historically used `app.models.chat_models.ChatMessage`.

To avoid defining a second `chat_messages` table (and breaking metadata / migrations),
we alias `ChatMessage` to the new model and keep only the legacy `ChatState` table.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.conversation import ChatMessage  # re-export for legacy imports


class ChatState(Base):
    __tablename__ = "chat_state"

    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.session_id"), primary_key=True)
    current_step = Column(String(50))
    context = Column(JSON, default=dict)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
