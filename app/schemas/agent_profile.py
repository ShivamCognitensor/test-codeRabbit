"""Pydantic schemas for Agent Profiles."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AgentProfileCreate(BaseModel):
    name: str = Field(..., max_length=120)
    description: Optional[str] = None
    language: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_template: Optional[str] = None
    pipeline_config: Optional[Dict[str, Any]] = None
    voice_config: Optional[Dict[str, Any]] = None
    analytics_config: Optional[Dict[str, Any]] = None
    is_active: bool = True


class AgentProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = None
    language: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_template: Optional[str] = None
    pipeline_config: Optional[Dict[str, Any]] = None
    voice_config: Optional[Dict[str, Any]] = None
    analytics_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class AgentProfileResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    language: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_template: Optional[str] = None
    pipeline_config: Optional[Dict[str, Any]] = None
    voice_config: Optional[Dict[str, Any]] = None
    analytics_config: Optional[Dict[str, Any]] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
