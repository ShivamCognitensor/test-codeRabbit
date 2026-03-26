from __future__ import annotations

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict


# ---------- HTTP CHAT ----------

class ChatMessageIn(BaseModel):
    session_id: UUID
    message: str = Field(..., min_length=1)


class ChatMessageOut(BaseModel):
    session_id: UUID
    reply: str
    current_step: Optional[str] = None


# ---------- AUDIO CHAT ----------

class AudioChatResponse(BaseModel):
    session_id: UUID
    transcript: str
    reply: str


# ---------- WEBSOCKET ----------

class WSClientHello(BaseModel):
    session_id: UUID
    language: Optional[str] = None


class WSError(BaseModel):
    type: str = "error"
    message: str


# ---------- SESSION ----------

class CreateSessionResponse(BaseModel):
    session_id: UUID
    created_at: datetime


class SessionMetaOut(BaseModel):
    session_id: UUID
    channel: str
    status: str
    created_at: datetime
    ended_at: Optional[datetime] = None
