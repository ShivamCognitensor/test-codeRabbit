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
    """
    Normalize a pipeline_config and ensure a local voicebot stack ID exists when using a local realtime provider.
    
    If pipeline_config is not a dict or does not specify a local realtime provider, it is returned unchanged. When realtime_provider == "local" and a valid voicebot_combo dict is present with both `stt_id` and `tts_id`, this function creates or resolves a voicebot stack and stores its ID in pipeline_config["voicebot_stack_id"].
    
    Returns:
        dict: The original or modified pipeline_config dictionary; includes `voicebot_stack_id` when a stack was created/resolved.
    
    Raises:
        HTTPException: 400 if required `stt_id` or `tts_id` are missing in voicebot_combo.
        HTTPException: 502 if the VoicebotClient reports a client-level error.
        HTTPException: 500 for any other unexpected error during stack creation/resolution.
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
    """
    List all AgentProfile records ordered by creation time (newest first).
    
    Returns:
        A success-response payload containing a list of serialized AgentProfileResponse dictionaries for each agent.
    """
    res = await db.execute(select(AgentProfile).order_by(AgentProfile.created_at.desc()))
    items = res.scalars().all()
    return success_response([AgentProfileResponse.model_validate(x).model_dump() for x in items])


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("voicebot.manage"))])
async def create_agent(payload: AgentProfileCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """
    Create a new AgentProfile from the provided payload and persist it to the database.
    
    Parameters:
        payload (AgentProfileCreate): Input data for the new agent; its `pipeline_config` will be normalized before saving.
    
    Returns:
        dict: The created AgentProfile serialized as an AgentProfileResponse and wrapped in the standard success response.
    """
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
    """
    Retrieve an AgentProfile by its UUID and return it as a serialized response.
    
    Parameters:
        agent_id (UUID): UUID of the AgentProfile to fetch.
    
    Returns:
        dict: A success response containing the serialized AgentProfileResponse.
    
    """
    obj = await db.get(AgentProfile, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")
    return success_response(AgentProfileResponse.model_validate(obj).model_dump())


@router.put("/{agent_id}", dependencies=[Depends(require_permission("voicebot.manage"))])
async def update_agent(agent_id: UUID, payload: AgentProfileUpdate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """
    Update fields of an existing AgentProfile and return the updated record.
    
    If `pipeline_config` is present in the update payload it will be normalized and possibly enriched before persisting (may create or assign a voicebot stack id).
    
    Parameters:
        payload (AgentProfileUpdate): Partial fields to apply to the AgentProfile; only provided fields are updated.
    
    Returns:
        dict: A success response containing the updated AgentProfile serialized as a dictionary.
    
    Raises:
        HTTPException: 404 if no AgentProfile with `agent_id` exists.
    """
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
    """
    Delete an AgentProfile identified by its UUID.
    
    Parameters:
        agent_id (UUID): UUID of the AgentProfile to delete.
        db (AsyncSession): Database session dependency.
        user: Current authenticated user dependency (unused in function).
    
    Returns:
        dict: Standard success response containing {"deleted": True}.
    
    Raises:
        HTTPException: 404 if the AgentProfile with the given UUID does not exist.
    """
    obj = await db.get(AgentProfile, agent_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(obj)
    await db.commit()
    return success_response({"deleted": True})
