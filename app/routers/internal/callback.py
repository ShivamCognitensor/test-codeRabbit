"""
Internal callback and webhook endpoints for voice bot integration.

Handles:
- Bolna.ai webhooks for call status updates
- Internal callbacks for custom voice bot engines
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, AliasChoices
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_internal_caller
from app.core.config import settings
from app.core.db import get_db
from app.models.campaign import CampaignContact
from app.services.voicebot_service import VoiceBotService
from shared.responses import success_response
from app.models.campaign import VoiceBotCampaign


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/voicebot", tags=["Internal - Voice Bot"])


# --------------------------------------------------------------------------------------
# Payload models
# --------------------------------------------------------------------------------------

class BolnaWebhookPayload(BaseModel):
    """
    Bolna webhook payload generally mirrors "Get Execution" response.
    Accept BOTH:
      - execution_id  (older internal shape)
      - id            (Bolna execution payload)
    """
    execution_id: str = Field(validation_alias=AliasChoices("execution_id", "id"))

    status: str
    transcript: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    telephony_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    @property
    def status_norm(self) -> str:
        # Bolna uses hyphenated statuses like "in-progress", "no-answer"
        return (self.status or "").strip().lower().replace("-", "_")

    @property
    def duration_seconds(self) -> Optional[int]:
        if isinstance(self.telephony_data, dict):
            return self.telephony_data.get("duration")
        return None

    @property
    def recording_url(self) -> Optional[str]:
        if isinstance(self.telephony_data, dict):
            return self.telephony_data.get("recording_url")
        return None


# --------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------

def verify_bolna_webhook(
    x_bolna_webhook_secret: Optional[str] = Header(None, alias="X-Bolna-Webhook-Secret"),
) -> bool:
    """
    Verify Bolna webhook secret if configured.
    If BOLNA_WEBHOOK_SECRET is empty, skip verification.
    """
    if not settings.BOLNA_WEBHOOK_SECRET:
        return True

    if x_bolna_webhook_secret != settings.BOLNA_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )
    return True


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

STATUS_MAPPING: Dict[str, str] = {
    # pre-call / setup
    "queued": "IN_PROGRESS",
    "initiated": "IN_PROGRESS",
    "ringing": "IN_PROGRESS",

    # active call
    "in_progress": "IN_PROGRESS",          # from "in-progress"

    # disconnect / finalization states
    "call_disconnected": "IN_PROGRESS",     # from "call-disconnected" (NOT final)
    "completed": "CONTACTED",               # final payload usually includes transcript/extracted_data

    # terminal negatives
    "no_answer": "NO_ANSWER",               # from "no-answer"
    "busy": "NO_ANSWER",
    "voicemail": "NO_ANSWER",

    "canceled": "FAILED",
    "failed": "FAILED",
}

STATUS_MAPPING.update({
    "busy": "NO_ANSWER",
    "no_answer": "NO_ANSWER",
    "failed": "FAILED",
    "canceled": "FAILED",
    "cancelled": "FAILED",
})

TERMINAL_NORMS = {"completed", "busy", "no_answer", "failed", "canceled", "cancelled"}


# def _calculate_qualification_score(extracted_data: Dict[str, Any]) -> int:
#     """
#     Calculate qualification score from extracted call data.

#     Scoring criteria:
#     - Interest expressed: +30 points
#     - Income provided: +20 points
#     - Employment confirmed: +20 points
#     - Loan amount specified: +15 points
#     - Positive sentiment: +15 points
#     """
#     score = 0
#     extracted_data = extracted_data or {}

#     # Interest
#     interest = extracted_data.get("interest") or extracted_data.get("interested")
#     if interest and str(interest).lower() in ["yes", "true", "high", "interested"]:
#         score += 30
#     elif interest and str(interest).lower() in ["maybe", "considering", "medium"]:
#         score += 15

#     # Income
#     if extracted_data.get("income") or extracted_data.get("monthly_income"):
#         score += 20

#     # Employment
#     employment = extracted_data.get("employment_type") or extracted_data.get("employed")
#     if employment:
#         score += 20

#     # Loan amount
#     if extracted_data.get("loan_amount") or extracted_data.get("amount_needed"):
#         score += 15

#     # Sentiment
#     sentiment = str(extracted_data.get("sentiment", "")).lower()
#     if sentiment in ["positive", "good", "interested"]:
#         score += 15
#     elif sentiment == "neutral":
#         score += 5

#     return min(100, score)

def _calculate_qualification_score(extracted: Dict[str, Any]) -> int:
    extracted = extracted or {}
    score = 0

    # Interest / intent (use your schema)
    intent = (extracted.get("loan_intent") or extracted.get("intent") or "").lower()
    loan_type = (extracted.get("loan_type") or "").lower()
    if intent in ["new_loan", "balance_transfer"] or "loan" in intent or loan_type:
        score += 30

    # Loan amount
    loan_amount = extracted.get("loan_amount") or extracted.get("loan_amount_inr") or extracted.get("amount_needed") or extracted.get("amount")
    if loan_amount:
        score += 15

    # Income
    income = extracted.get("monthly_income") or extracted.get("monthly_income_inr") or extracted.get("income") or extracted.get("annual_income_inr")
    if income:
        score += 20

    # Employment
    employment = extracted.get("employment_type") or extracted.get("employment_status") or extracted.get("employed")
    if employment:
        score += 20

    # Callback time (very strong signal)
    if extracted.get("preferred_callback_time"):
        score += 15

    return min(100, score)


async def _fallback_post_call_analytics(service: VoiceBotService, transcript: str) -> Dict[str, Any]:
    """
    Optional fallback: if Bolna doesn't send extracted_data but transcript exists,
    try to run your own post-call analytics (open-source LLM) if the service supports it.

    This keeps callback file robust even if analytics method doesn't exist yet.
    """
    if not transcript:
        return {}

    # If you implemented this in VoiceBotService, it will be used.
    fn = getattr(service, "run_post_call_analytics", None)
    if callable(fn):
        try:
            return await fn(transcript) or {}
        except Exception:
            logger.exception("Fallback analytics failed via VoiceBotService.run_post_call_analytics")
            return {}

    # No fallback implemented -> return empty
    return {}


# --------------------------------------------------------------------------------------
# Webhooks
# --------------------------------------------------------------------------------------

# @router.post("/bolna/webhook")
# async def bolna_webhook(
#     payload: BolnaWebhookPayload,
#     request: Request,
#     db: AsyncSession = Depends(get_db),
#     verified: bool = Depends(verify_bolna_webhook),
# ):
#     """
#     Webhook endpoint for Bolna.ai call status updates.
#     Bolna sends multiple updates; final useful update is usually 'completed'.
#     """
#     logger.info(
#         "Bolna webhook: execution_id=%s status=%s norm=%s",
#         payload.execution_id,
#         payload.status,
#         payload.status_norm,
#     )

#     # Find contact by Bolna execution ID
#     result = await db.execute(
#         select(CampaignContact).where(CampaignContact.bolna_execution_id == payload.execution_id)
#     )
#     contact = result.scalars().first()

#     if not contact:
#         logger.warning("Contact not found for execution_id=%s", payload.execution_id)
#         return success_response(
#             message="Webhook received (contact not found)",
#             data={"execution_id": payload.execution_id, "status": payload.status},
#         )

#     # If already finalized, keep storing late metadata but do not re-run finalization.
#     already_final = contact.status in ("QUALIFIED", "DISQUALIFIED")

#     # Compute next status using normalized mapping
#     mapped_status = STATUS_MAPPING.get(payload.status_norm)

#     # For unknown statuses, do not force CONTACTED; keep current or mark IN_PROGRESS
#     if mapped_status is None:
#         mapped_status = contact.status or "IN_PROGRESS"

#     # Update basic metadata always (safe + useful)
#     contact.status = mapped_status
#     if payload.duration_seconds is not None:
#         # contact.call_duration_seconds = payload.duration_seconds
#         duration = getattr(payload, "call_duration_seconds", None) or getattr(payload, "call_duration", None)
#         try:
#             contact.call_duration_seconds = int(float(duration)) if duration is not None else None
#         except (TypeError, ValueError):
#             contact.call_duration_seconds = None
#     if payload.recording_url:
#         contact.recording_url = payload.recording_url
#     if payload.transcript:
#         contact.transcript = payload.transcript
#     if payload.extracted_data:
#         contact.collected_data = {**(contact.collected_data or {}), **payload.extracted_data}

#     # If already finalized, just commit metadata and return
#     if already_final:
#         try:
#             await db.commit()
#         except Exception:
#             await db.rollback()
#             raise
#         return success_response(
#             message="Webhook processed (already finalized)",
#             data={"execution_id": payload.execution_id, "contact_id": str(contact.id), "status": contact.status},
#         )

#     # Finalization should happen on completed
#     if payload.status_norm == "completed":
#         service = VoiceBotService(db)

#         extracted = payload.extracted_data or {}
#         transcript = payload.transcript or contact.transcript

#         # If Bolna didn't send extracted_data, try our fallback analytics (optional)
#         if not extracted and transcript:
#             extracted = await _fallback_post_call_analytics(service, transcript)

#             # persist extracted into collected_data if we got any
#             if extracted:
#                 contact.collected_data = {**(contact.collected_data or {}), **extracted}

#         # Qualification decision: only if we have something to score; otherwise keep CONTACTED
#         if extracted:
#             qualification_score = _calculate_qualification_score(extracted)
#             final_status = "QUALIFIED" if qualification_score >= 60 else "DISQUALIFIED"

#             # process_call_result should commit
#             await service.process_call_result(
#                 contact_id=contact.id,
#                 status=final_status,
#                 call_duration=payload.duration_seconds,
#                 responses=extracted,
#                 qualification_score=qualification_score,
#                 collected_data=extracted,
#             )
#         else:
#             # No extracted data and no fallback -> just commit what we stored (CONTACTED/transcript/etc.)
#             await db.commit()

#         return success_response(
#             message="Webhook processed",
#             data={"execution_id": payload.execution_id, "contact_id": str(contact.id), "status": contact.status},
#         )

#     # For non-completed statuses, just commit the status/meta update
#     await db.commit()
#     return success_response(
#         message="Webhook processed",
#         data={"execution_id": payload.execution_id, "contact_id": str(contact.id), "status": contact.status},
#     )


@router.post("/bolna/webhook")
async def bolna_webhook(
    payload: BolnaWebhookPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    verified: bool = Depends(verify_bolna_webhook),
):
    logger.info(
        "Bolna webhook: execution_id=%s status=%s norm=%s",
        payload.execution_id,
        payload.status,
        payload.status_norm,
    )

    result = await db.execute(
        select(CampaignContact).where(CampaignContact.bolna_execution_id == payload.execution_id)
    )
    contact = result.scalars().first()

    if not contact:
        logger.warning("Contact not found for execution_id=%s", payload.execution_id)
        return success_response(
            message="Webhook received (contact not found)",
            data={"execution_id": payload.execution_id, "status": payload.status},
        )

    # already_final = contact.status in ("QUALIFIED", "DISQUALIFIED")
    already_final = contact.status in ("QUALIFIED", "DISQUALIFIED", "NO_ANSWER", "FAILED")


    mapped_status = STATUS_MAPPING.get(payload.status_norm)
    if mapped_status is None:
        mapped_status = contact.status or "IN_PROGRESS"

    if not already_final:
        contact.status = mapped_status

        # Keep dashboard-friendly call_outcome tokens updated for intermediate/terminal non-completed callbacks.
        if payload.status_norm in {"queued", "initiated", "ringing", "in_progress", "call_disconnected"}:
            contact.call_outcome = "ONGOING_CALL"
        elif payload.status_norm in {"no_answer", "busy", "voicemail"}:
            contact.call_outcome = "NO_ANSWER_CALL"
        elif payload.status_norm in {"failed", "canceled", "cancelled"}:
            contact.call_outcome = "NOT_CONNECT"

    duration_val = (
        getattr(payload, "duration_seconds", None)
        or getattr(payload, "call_duration_seconds", None)
        or getattr(payload, "call_duration", None)
    )
    try:
        contact.call_duration_seconds = (
            int(float(duration_val)) if duration_val is not None else contact.call_duration_seconds
        )
    except (TypeError, ValueError):
        pass

    if payload.recording_url:
        contact.recording_url = payload.recording_url

    if payload.transcript:
        contact.transcript = payload.transcript

    if payload.extracted_data:
        contact.collected_data = {**(contact.collected_data or {}), **payload.extracted_data}

    # If already finalized: commit metadata, and if this is a duplicate "completed", still kick next safely.
    if already_final:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        if payload.status_norm == "completed":
            service = VoiceBotService(db)
            campaign = await db.get(VoiceBotCampaign, contact.campaign_id)
            if campaign and campaign.status == "RUNNING":
                await service._trigger_bolna_campaign(campaign)

        return success_response(
            message="Webhook processed (already finalized)",
            data={"execution_id": payload.execution_id, "contact_id": str(contact.id), "status": contact.status},
        )

    # Finalization should happen on completed
    if payload.status_norm == "completed":
        service = VoiceBotService(db)

        extracted = payload.extracted_data or {}
        transcript = payload.transcript or contact.transcript

        if not extracted and transcript:
            extracted = await _fallback_post_call_analytics(service, transcript) or {}

        if extracted:
            loan_amount = extracted.get("loan_amount") or extracted.get("loan_amount_inr")
            income = extracted.get("monthly_income") or extracted.get("monthly_income_inr")

            if loan_amount is not None:
                extracted.setdefault("loan_amount", loan_amount)
                extracted.setdefault("amount", loan_amount)
            if income is not None:
                extracted.setdefault("monthly_income", income)
                extracted.setdefault("income", income)

            merged_collected = {**(contact.collected_data or {}), **extracted}
            contact.collected_data = merged_collected

            qualification_score = _calculate_qualification_score(extracted)
            final_status = "QUALIFIED" if qualification_score >= 50 else "DISQUALIFIED"

            contact = await service.process_call_result(
                contact_id=contact.id,
                status=final_status,
                call_duration=contact.call_duration_seconds,
                responses=extracted,
                qualification_score=qualification_score,
                collected_data=merged_collected,
            )
        else:
            await db.commit()

        # Best-effort post-call analytics (stores into collected_data.post_call_analytics)
        try:
            transcript_text = (transcript or "").strip()
            if transcript_text:
                await service.run_post_call_analytics(contact=contact, transcript=transcript_text)
        except Exception:
            logger.exception("post_call_analytics_failed")

        # NEW: trigger next pending contact (sequential calling)
        campaign = await db.get(VoiceBotCampaign, contact.campaign_id)
        if campaign and campaign.status == "RUNNING":
            await service._trigger_bolna_campaign(campaign)

        return success_response(
            message="Webhook processed",
            data={"execution_id": payload.execution_id, "contact_id": str(contact.id), "status": contact.status},
        )

    # Terminal non-completed statuses should update counters via the same processing path
    if payload.status_norm in {"busy", "no_answer", "failed", "canceled", "cancelled"}:
        service = VoiceBotService(db)
        try:
            contact = await service.process_call_result(
                contact_id=contact.id,
                status=mapped_status,
                call_duration=contact.call_duration_seconds,
                responses=contact.responses or {},
                collected_data=contact.collected_data or {},
            )
        except Exception:
            logger.exception("process_terminal_status_failed")
            await db.commit()

        campaign = await db.get(VoiceBotCampaign, contact.campaign_id)
        if campaign and campaign.status == "RUNNING":
            await service._trigger_bolna_campaign(campaign)

        return success_response(
            message="Webhook processed",
            data={"execution_id": payload.execution_id, "contact_id": str(contact.id), "status": contact.status},
        )

    await db.commit()
    return success_response(
        message="Webhook processed",
        data={"execution_id": payload.execution_id, "contact_id": str(contact.id), "status": contact.status},
    )



@router.get("/bolna/webhook/health")
async def bolna_webhook_health():
    """Health check for Bolna webhook endpoint."""
    return success_response(message="Webhook endpoint healthy", data={"status": "ok"})


# --------------------------------------------------------------------------------------
# Generic internal callback (for custom voice bot engines)
# --------------------------------------------------------------------------------------

@router.post("/callback")
async def call_callback(
    contact_id: UUID,
    status: str,
    call_duration: Optional[int] = None,
    responses: Optional[Dict[str, Any]] = None,
    qualification_score: Optional[int] = None,
    collected_data: Optional[Dict[str, Any]] = None,
    db: AsyncSession = Depends(get_db),
    caller: Optional[str] = Depends(get_internal_caller),
):
    """
    Generic callback endpoint for custom voice bot engines.
    Called by an external voice bot provider after each call.
    """
    service = VoiceBotService(db)

    contact = await service.process_call_result(
        contact_id=contact_id,
        status=status,
        call_duration=call_duration,
        responses=responses,
        qualification_score=qualification_score,
        collected_data=collected_data,
    )

    return success_response(
        message="Call result processed",
        data={
            "contact_id": str(contact.id),
            "status": contact.status,
            "lead_id": str(contact.lead_id) if contact.lead_id else None,
        },
    )
