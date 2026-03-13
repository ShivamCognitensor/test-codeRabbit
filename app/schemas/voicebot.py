"""Pydantic schemas for Voice Bot campaigns.

The frontend (Figma/PDF) uses camelCase fields like:
- campaignStartDate, campaignEndDate
- campaignStartTime, campaignEndTime
- timeMode, selectedDays
- loanType, model, voiceGender, campaignMode

We accept those names via `validation_alias` so the UI can post them directly.
We also keep older snake_case fields for backwards compatibility.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, AliasChoices, ConfigDict


class CampaignCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Campaign detail
    name: str
    description: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("description", "desc"),
        serialization_alias="description",
    )

    campaign_type: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("campaign_type", "campaignType"),
        serialization_alias="campaign_type",
    )

    # Schedule fields (UI)
    multiple_day: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("multiple_day", "multipleDay"),
        serialization_alias="multiple_day",
    )
    single_day: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("single_day", "singleDay"),
        serialization_alias="single_day",
    )

    campaign_start_date: Optional[date] = Field(
        default=None,
        validation_alias=AliasChoices("campaign_start_date", "campaignStartDate"),
        serialization_alias="campaign_start_date",
    )
    campaign_end_date: Optional[date] = Field(
        default=None,
        validation_alias=AliasChoices("campaign_end_date", "campaignEndDate"),
        serialization_alias="campaign_end_date",
    )

    campaign_start_time: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("campaign_start_time", "campaignStartTime"),
        serialization_alias="campaign_start_time",
    )
    campaign_end_time: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("campaign_end_time", "campaignEndTime"),
        serialization_alias="campaign_end_time",
    )

    time_mode: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("time_mode", "timeMode"),
        serialization_alias="time_mode",
    )
    selected_days: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("selected_days", "selectedDays"),
        serialization_alias="selected_days",
    )

    # Campaign config fields (UI)
    loan_type: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("loan_type", "loanType"),
        serialization_alias="loan_type",
    )
    ai_model: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("ai_model", "model"),
        serialization_alias="ai_model",
    )
    voice_gender: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("voice_gender", "voiceGender"),
        serialization_alias="voice_gender",
    )
    campaign_mode: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("campaign_mode", "campaignMode"),
        serialization_alias="campaign_mode",
    )

    # Script/assistant
    agent_profile_id: Optional[UUID] = Field(
        default=None,
        validation_alias=AliasChoices("agent_profile_id", "agentProfileId"),
        serialization_alias="agent_profile_id",
    )

    # Backwards compatible fields
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None

    script_config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # All fields optional for wizard step updates
    name: Optional[str] = None
    description: Optional[str] = Field(default=None, validation_alias=AliasChoices("description", "desc"))

    campaign_type: Optional[str] = Field(default=None, validation_alias=AliasChoices("campaign_type", "campaignType"))

    multiple_day: Optional[bool] = Field(default=None, validation_alias=AliasChoices("multiple_day", "multipleDay"))
    single_day: Optional[bool] = Field(default=None, validation_alias=AliasChoices("single_day", "singleDay"))

    campaign_start_date: Optional[date] = Field(default=None, validation_alias=AliasChoices("campaign_start_date", "campaignStartDate"))
    campaign_end_date: Optional[date] = Field(default=None, validation_alias=AliasChoices("campaign_end_date", "campaignEndDate"))

    campaign_start_time: Optional[str] = Field(default=None, validation_alias=AliasChoices("campaign_start_time", "campaignStartTime"))
    campaign_end_time: Optional[str] = Field(default=None, validation_alias=AliasChoices("campaign_end_time", "campaignEndTime"))

    time_mode: Optional[str] = Field(default=None, validation_alias=AliasChoices("time_mode", "timeMode"))
    selected_days: Optional[List[str]] = Field(default=None, validation_alias=AliasChoices("selected_days", "selectedDays"))

    loan_type: Optional[str] = Field(default=None, validation_alias=AliasChoices("loan_type", "loanType"))
    ai_model: Optional[str] = Field(default=None, validation_alias=AliasChoices("ai_model", "model"))
    voice_gender: Optional[str] = Field(default=None, validation_alias=AliasChoices("voice_gender", "voiceGender"))
    campaign_mode: Optional[str] = Field(default=None, validation_alias=AliasChoices("campaign_mode", "campaignMode"))

    agent_profile_id: Optional[UUID] = Field(default=None, validation_alias=AliasChoices("agent_profile_id", "agentProfileId"))

    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None

    script_config: Optional[Dict[str, Any]] = None


class CampaignResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None

    campaign_type: Optional[str] = None
    loan_type: Optional[str] = None
    ai_model: Optional[str] = None
    voice_gender: Optional[str] = None
    campaign_mode: Optional[str] = None

    agent_profile_id: Optional[UUID] = None

    status: str
    schedule_config: Dict[str, Any] = Field(default_factory=dict)

    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None

    total_contacts: int = 0
    contacted: int = 0
    qualified: int = 0
    disqualified: int = 0
    no_answer: int = 0
    leads_created: int = 0

    source_file: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ContactCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    phone: str
    name: Optional[str] = None
    pincode: Optional[str] = None
    location: Optional[str] = None


class ContactResponse(BaseModel):
    id: UUID
    campaign_id: UUID

    phone: str
    name: Optional[str] = None
    pincode: Optional[str] = None
    location: Optional[str] = None

    status: str
    call_outcome: Optional[str] = None
    callback_needed: bool = False

    call_attempts: int = 0
    last_call_at: Optional[datetime] = None
    call_duration_seconds: Optional[int] = None

    qualification_score: Optional[int] = None
    responses: Dict[str, Any] = Field(default_factory=dict)
    collected_data: Dict[str, Any] = Field(default_factory=dict)

    bolna_execution_id: Optional[str] = None
    recording_url: Optional[str] = None
    transcript: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class CampaignContactResponse(ContactResponse):
    pass

class ContactsUploadResponse(BaseModel):
    message: str
    total_added: int
    invalid_count: int = 0


class CampaignListResponse(BaseModel):
    campaigns: List[CampaignResponse]
    total: int
    page: int
    page_size: int


class DashboardOverviewResponse(BaseModel):
    total_campaigns: int
    active_campaigns: int
    paused_campaigns: int
    completed_calls: int


class CampaignMetricsResponse(BaseModel):
    total_calls: int
    answered_calls: int
    no_answer_calls: int
    rejected_calls: int
    callback_need_calls: int


class CallsListResponse(BaseModel):
    calls: List[ContactResponse]
    total: int
    page: int
    page_size: int

