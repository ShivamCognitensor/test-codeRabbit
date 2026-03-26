from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_profile import AgentProfile
from app.models.campaign import CampaignContact
from app.services.analytics.post_call import extract_post_call_analytics
from app.services.voicebot_service import VoiceBotService

logger = get_logger(__name__)


def _transcript_to_text(transcript: list[dict[str, Any]]) -> str:
    # transcript list is [{role,text},...]
    lines = []
    for item in transcript or []:
        role = item.get("role") or ""
        text = item.get("text") or ""
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines).strip()


async def finalize_call(
    db: AsyncSession,
    contact_id: Optional[UUID],
    agent_profile_id: Optional[UUID],
    transcript: list[dict[str, Any]],
    provider_meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Finalize a streamed call:
    - persist transcript
    - run analytics
    - mark QUALIFIED/DISQUALIFIED + create lead (existing VoiceBotService logic)
    """
    if not contact_id:
        return

    contact = await db.get(CampaignContact, contact_id)
    if not contact:
        return

    agent: Optional[AgentProfile] = None
    if agent_profile_id:
        agent = await db.get(AgentProfile, agent_profile_id)

    transcript_text = _transcript_to_text(transcript)
    # analytics schema can be passed from agent.analytics_config.schema if present
    schema = None
    provider = None
    model = None
    if agent and isinstance(agent.analytics_config, dict):
        schema = agent.analytics_config.get("schema")
        provider = agent.analytics_config.get("provider")
        model = agent.analytics_config.get("model")

    analytics = {}
    if transcript_text:
        analytics = await extract_post_call_analytics(transcript_text, schema=schema, provider=provider, model=model)

    qualified = bool(analytics.get("qualified")) if isinstance(analytics, dict) else False
    score = None
    if isinstance(analytics, dict):
        try:
            score = int(analytics.get("qualification_score")) if analytics.get("qualification_score") is not None else None
        except Exception:
            score = None

    collected = {}
    if isinstance(analytics, dict):
        lead = analytics.get("lead")
        if isinstance(lead, dict):
            collected.update(lead)

    # store transcript + analytics under responses/collected_data
    responses = {
        "transcript": transcript_text,
        "raw_transcript": transcript,
        "provider_meta": provider_meta or {},
        "analytics": analytics,
    }

    status = "QUALIFIED" if qualified else "DISQUALIFIED"

    try:
        svc = VoiceBotService(db)
        await svc.process_call_result(
            contact_id=contact.id,
            status=status,
            call_duration=None,
            responses=responses,
            qualification_score=score,
            collected_data=collected,
        )
    except Exception:
        logger.exception("finalize_call_failed")
