"""Agent profiles: dynamic prompt + model/voice configuration.

A profile represents a plug-and-play voice agent configuration that the frontend can edit:
- system prompt / prompt template (variables supported)
- telephony settings (provider defaults)
- model pipeline (audio-to-audio vs classic STT->LLM->TTS)
- voice selection (provider + voice id / accents)
- post-call analytics model configuration
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.db import Base, AuditMixin


class AgentProfile(Base, AuditMixin):
    __tablename__ = "agent_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    name = Column(String(120), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # language hints: 'en', 'hi', 'en-IN', etc
    language = Column(String(32), nullable=True)

    # prompt controls
    system_prompt = Column(Text, nullable=True)
    prompt_template = Column(Text, nullable=True)  # optional, can include {{variables}}

    # pipeline config (JSON so it's easy to extend)
    # example:
    # {
    #   "type": "audio2audio",
    #   "realtime_provider": "openai",
    #   "realtime_model": "gpt-realtime",
    #   "input_audio_format": "g711_ulaw",
    #   "output_audio_format": "g711_ulaw"
    # }
    pipeline_config = Column(JSONB, nullable=True)

    # voice config (provider-specific)
    # { "provider": "openai|elevenlabs|fish|kokoro", "voice_id": "...", "style": "...", "accent": "hi-IN" }
    voice_config = Column(JSONB, nullable=True)

    # post-call analytics config
    # { "provider": "openai|openai_compat|local", "model": "...", "schema": {...} }
    analytics_config = Column(JSONB, nullable=True)

    # Whether this profile is active/usable from UI
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
