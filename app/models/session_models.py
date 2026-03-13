import uuid
from sqlalchemy import Column, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.db.base import Base
from app.models.enums import SessionChannel, SessionStatus


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    channel = Column(Enum(SessionChannel), nullable=False)
    status = Column(Enum(SessionStatus), default=SessionStatus.active)
    created_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime)
