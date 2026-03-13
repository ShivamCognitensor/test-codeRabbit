"""Agent Profile CRUD endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_permission
from app.core.db import get_db
from app.models.agent_profile import AgentProfile
from app.schemas.agent_profile import AgentProfileCreate, AgentProfileResponse, AgentProfileUpdate
from app.clients.voicebot_client import VoicebotClient, VoicebotClientError
from shared.responses import success_response

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])


async def _normalize_pipeline_config(pipeline_config):
    """Normalize pipeline_config for persisted AgentProfile records.

    If the frontend provides a mix-and-match local model selection under
    pipeline_config.voicebot_combo, LMS resolves/creates a Voicebot stack_id
    and stores it in pipeline_config.voicebot_stack_id.

    This ensures runtime remains stack_id-driven (fast + cache-friendly).
    """
    if not pipeline_config or not isinstance(pipeline_config, dict):
        return pipeline_config

    realtime_provider = (pipeline_config.get("realtime_provider") or "").strip().lower()
    if realtime_provider != "local":
        return pipeline_config

    combo = pipeline_config.get("voicebot_combo")
    if not combo or not isinstance(combo, dict):
        return pipeline_config

    stt_id = (combo.get("stt_id") or "").strip()
    llm_id = (combo.get("llm_id") or None)
    llm_id = llm_id.strip() if isinstance(llm_id, str) and llm_id.strip() else None
    tts_id = (combo.get("tts_id") or "").strip()
    if not stt_id or not tts_id:
        raise HTTPException(status_code=400, detail="voicebot_combo requires stt_id and tts_id")

    # Optional naming. If not provided, Voicebot generates a deterministic stack id.
    requested_stack_id = (pipeline_config.get("voicebot_stack_id") or "").strip() or None
    label = (pipeline_config.get("voicebot_stack_label") or pipeline_config.get("local_model_label") or "").strip() or None

    try:
        client = VoicebotClient.from_settings()
        created_stack_id = await client.create_stack(stt_id=stt_id, llm_id=llm_id, tts_id=tts_id, stack_id=requested_stack_id, label=label)
    except VoicebotClientError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    pipeline_config["voicebot_stack_id"] = created_stack_id
    return pipeline_config


@router.get("", dependencies=[Depends(require_permission("voicebot.view"))])
async def list_agents(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    res = await db.execute(select(AgentProfile).order_by(AgentProfile.created_at.desc()))
    items = res.scalars().all()
    return success_response([AgentProfileResponse.model_validate(x).model_dump() for x in items])


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("voicebot.manage"))])
async def create_agent(payload: AgentProfileCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    pipeline_config = await _normalize_pipeline_config(payload.pipeline_config)
    obj = AgentProfile(
        name=payload.name,
        description=payload.description,
        language=payload.language,
        system_prompt=payload.system_prompt,
        prompt_template=payload.prompt_template,
        pipeline_config=pipeline_config,
        voice_config=payload.voice_config,
        analytics_config=payload.analytics_config,
        is_active=payload.is_active,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return success_response(AgentProfileResponse.model_validate(obj).model_dump())


@router.get("/{agent_id}", dependencies=[Depends(require_permission("voicebot.view"))])
async def get_agent(agent_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    obj = await db.get(AgentProfile, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")
    return success_response(AgentProfileResponse.model_validate(obj).model_dump())


@router.put("/{agent_id}", dependencies=[Depends(require_permission("voicebot.manage"))])
async def update_agent(agent_id: UUID, payload: AgentProfileUpdate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    obj = await db.get(AgentProfile, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")

    data = payload.model_dump(exclude_unset=True)
    if "pipeline_config" in data:
        data["pipeline_config"] = await _normalize_pipeline_config(data.get("pipeline_config"))
    for k, v in data.items():
        setattr(obj, k, v)

    await db.commit()
    await db.refresh(obj)
    return success_response(AgentProfileResponse.model_validate(obj).model_dump())


@router.delete("/{agent_id}", dependencies=[Depends(require_permission("voicebot.manage"))])
async def delete_agent(agent_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    obj = await db.get(AgentProfile, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(obj)
    await db.commit()
    return success_response({"deleted": True})
