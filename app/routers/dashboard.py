"""Dashboard endpoints for Voice Bot / Audio Bot operations.

These endpoints are used by UI dashboards and reporting screens.
They intentionally provide *richer* payloads than the operational endpoints.

Scope (as requested):
- Chat bot
- Audio bot (voicebot campaigns)
- Campaign settings + dashboard
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.core.db import get_db
from app.models.campaign import CampaignContact, VoiceBotCampaign
from app.clients.lead_ops_client import lead_ops_client
from shared.responses import success_response


router = APIRouter(prefix="/api/v1/voicebot/dashboard", tags=["Voice Bot - Dashboard"])


@router.get("/overview")
async def dashboard_overview(
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Return dashboard-level KPIs and aggregated metrics for all voice bot campaigns.
    
    Returns:
        dict: Response payload containing a `data` object with:
            - kpis (dict): High-level counts:
                - total_campaigns (int)
                - active_campaigns (int)
                - paused_campaigns (int)
                - completed_calls (int)
            - campaigns (dict):
                - total (int)
                - running (int)
            - calls (dict):
                - total_contacts (int)
                - contacted (int)
                - qualified (int)
                - leads_created (int)
                - conversion_rate_pct (float): Percentage (0-100) rounded to two decimals.
                - avg_duration_seconds (int|None): Average call duration in seconds or None if unavailable.
                - avg_qualification_score (float|None): Average qualification score or None if unavailable.
    """

    # Campaign counts
    total_campaigns = (await db.execute(select(func.count()).select_from(VoiceBotCampaign))).scalar() or 0
    running_campaigns = (
        (await db.execute(select(func.count()).select_from(VoiceBotCampaign).where(VoiceBotCampaign.status == "RUNNING")))
        .scalar()
        or 0
    )

    paused_campaigns = (
        (await db.execute(select(func.count()).select_from(VoiceBotCampaign).where(VoiceBotCampaign.status == "PAUSED")))
        .scalar()
        or 0
    )

    # Contact / call counts
    total_contacts = (await db.execute(select(func.count()).select_from(CampaignContact))).scalar() or 0
    contacted = (
        (await db.execute(select(func.count()).select_from(CampaignContact).where(CampaignContact.status != "PENDING")))
        .scalar()
        or 0
    )

    completed_calls = (
        (await db.execute(
            select(func.count()).select_from(CampaignContact).where(
                CampaignContact.status.not_in(["PENDING", "INVALID"])
            )
        )).scalar()
        or 0
    )
    qualified = (
        (await db.execute(select(func.count()).select_from(CampaignContact).where(CampaignContact.status == "QUALIFIED")))
        .scalar()
        or 0
    )
    leads_created = (
        (await db.execute(select(func.count()).select_from(CampaignContact).where(CampaignContact.lead_id.is_not(None))))
        .scalar()
        or 0
    )
    avg_duration = (
        (await db.execute(select(func.avg(CampaignContact.call_duration_seconds)).where(CampaignContact.call_duration_seconds.is_not(None))))
        .scalar()
    )
    avg_score = (
        (await db.execute(select(func.avg(CampaignContact.qualification_score)).where(CampaignContact.qualification_score.is_not(None))))
        .scalar()
    )

    conversion_rate = (leads_created / contacted * 100.0) if contacted else 0.0

    return success_response(
        message="Dashboard overview",
        data={
            "kpis": {
                "total_campaigns": int(total_campaigns),
                "active_campaigns": int(running_campaigns),
                "paused_campaigns": int(paused_campaigns),
                "completed_calls": int(completed_calls),
            },
            "campaigns": {
                "total": int(total_campaigns),
                "running": int(running_campaigns),
            },
            "calls": {
                "total_contacts": int(total_contacts),
                "contacted": int(contacted),
                "qualified": int(qualified),
                "leads_created": int(leads_created),
                "conversion_rate_pct": round(conversion_rate, 2),
                "avg_duration_seconds": int(avg_duration) if avg_duration is not None else None,
                "avg_qualification_score": float(avg_score) if avg_score is not None else None,
            },
        },
    )


@router.get("/campaigns/{campaign_id}/metrics")
async def campaign_metrics(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """Campaign-level metrics used by dashboards."""

    campaign = (
        (await db.execute(select(VoiceBotCampaign).where(VoiceBotCampaign.id == campaign_id))).scalars().first()
    )
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    # Internal status breakdown (engine) + UI outcome breakdown (dashboard)
    status_counts = dict(
        (await db.execute(
            select(CampaignContact.status, func.count())
            .where(CampaignContact.campaign_id == campaign_id)
            .group_by(CampaignContact.status)
        )).all()
    )

    outcome_counts = dict(
        (await db.execute(
            select(CampaignContact.call_outcome, func.count())
            .where(CampaignContact.campaign_id == campaign_id)
            .group_by(CampaignContact.call_outcome)
        )).all()
    )

    def _outcome(*keys: str) -> int:
        """
        Sum the integer counts for the given outcome keys from the `outcome_counts` mapping.
        
        Parameters:
            keys (str): One or more outcome keys to aggregate; each key is looked up in `outcome_counts`.
        
        Returns:
            total (int): Sum of counts for the provided keys. Missing or falsy entries in `outcome_counts` are treated as zero.
        """
        total = 0
        for k in keys:
            total += int(outcome_counts.get(k) or 0)
        return total

    total_calls = int(campaign.total_contacts or 0)
    answered_calls = _outcome("ANSWERED_CALL", "ANSWERED")
    rejected_calls = _outcome("REJECTED_CALL", "REJECTED")
    callback_need_calls = _outcome("CALLBACK_NEED", "CALLBACK_NEEDED")
    no_answer_calls = _outcome("NO_ANSWER_CALL", "NO_ANSWER", "NOT_CONNECT")

    # Averages
    avg_duration = (
        (await db.execute(
            select(func.avg(CampaignContact.call_duration_seconds))
            .where(
                CampaignContact.campaign_id == campaign_id,
                CampaignContact.call_duration_seconds.is_not(None),
            )
        )).scalar()
    )
    avg_score = (
        (await db.execute(
            select(func.avg(CampaignContact.qualification_score))
            .where(
                CampaignContact.campaign_id == campaign_id,
                CampaignContact.qualification_score.is_not(None),
            )
        )).scalar()
    )

    contacted = int((campaign.contacted or 0))
    leads_created = int((campaign.leads_created or 0))
    conversion_rate = (leads_created / contacted * 100.0) if contacted else 0.0

    return success_response(
        message="Campaign metrics",
        data={
            "campaign": {
                "id": str(campaign.id),
                "name": campaign.name,
                "status": campaign.status,
                "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
                "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
            },
            "status_breakdown": {k: int(v) for k, v in status_counts.items()},
            "outcome_breakdown": {str(k): int(v) for k, v in outcome_counts.items()},
            "call_metrics": {
                "total_calls": total_calls,
                "answered_calls": answered_calls,
                "no_answer_calls": no_answer_calls,
                "rejected_calls": rejected_calls,
                "callback_need_calls": callback_need_calls,
            },
            "stats": {
                "total_contacts": total_calls,
                "contacted": contacted,
                "qualified": int(campaign.qualified or 0),
                "disqualified": int(campaign.disqualified or 0),
                "no_answer": int(campaign.no_answer or 0),
                "leads_created": leads_created,
                "conversion_rate_pct": round(conversion_rate, 2),
                "avg_duration_seconds": int(avg_duration) if avg_duration is not None else None,
                "avg_qualification_score": float(avg_score) if avg_score is not None else None,
            },
        },
    )


@router.get("/campaigns/{campaign_id}/calls")
async def campaign_calls(
    campaign_id: UUID,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_transcript: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Retrieve a paginated list of calls/contacts for a campaign, shaped for dashboard display.
    
    Parameters:
        status_filter (Optional[str]): Filter contacts by their status (query alias "status"); if omitted, no status filtering is applied.
        page (int): Page number (1-based) of results to return.
        page_size (int): Number of items per page (bounded by 1–200).
        include_transcript (bool): If true, include the full transcript for each contact; otherwise include a truncated snippet.
        
    Returns:
        dict: Response payload containing:
            - items (list[dict]): List of contact summaries. Each item includes keys such as:
                `id`, `phone`, `name`, `pincode`, `location`, `status`, `call_outcome`,
                `status_label`, `callback_needed`, `call_attempts`, `last_call_at`,
                `call_duration_seconds`, `qualification_score`, `lead_id`, `recording_url`,
                `transcript`, `bolna_execution_id`, `analysis`, and `ui_flags`.
            - total (int): Total number of matching contacts.
            - page (int): Echo of the requested page number.
            - page_size (int): Echo of the requested page size.
    """

    q = select(CampaignContact).where(CampaignContact.campaign_id == campaign_id)
    if status_filter:
        q = q.where(CampaignContact.status == status_filter)

    total = (
        (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
        or 0
    )

    offset = (page - 1) * page_size
    q = q.order_by(CampaignContact.created_at.desc()).offset(offset).limit(page_size)
    contacts = (await db.execute(q)).scalars().all()

    def _snippet(text: Optional[str], limit: int = 220) -> Optional[str]:
        """
        Produce a truncated preview of a text string limited to a maximum number of characters.
        
        Parameters:
            text (Optional[str]): The input text to truncate. If `None` or empty, the function returns `None`.
            limit (int): Maximum number of characters allowed before truncation; defaults to 220.
        
        Returns:
            Optional[str]: The original text if its length is less than or equal to `limit`; otherwise a truncated string of length `limit` followed by an ellipsis ("..."). Returns `None` for `None` or empty input.
        """
        if not text:
            return None
        return text if len(text) <= limit else text[:limit] + "..."

    items = []
    for c in contacts:
        # Map stored outcome tokens to the UI labels shown in Figma.
        outcome = c.call_outcome or ""
        label_map = {
            "NOT_CONNECT": "Not Connect",
            "ONGOING_CALL": "Ongoing Call",
            "ANSWERED_CALL": "Answered Call",
            "NO_ANSWER_CALL": "No Answer Call",
            "REJECTED_CALL": "Rejected Call",
            "CALLBACK_NEED": "Call Back Need",
            "INCORRECT_ENTRY": "Incorrect Entry",
        }
        status_label = label_map.get(outcome, outcome or c.status)
        items.append(
            {
                "id": str(c.id),
                "phone": c.phone,
                "name": c.name,
                "pincode": c.pincode,
                "location": c.location,
                "status": c.status,
                "call_outcome": c.call_outcome,
                "status_label": status_label,
                "callback_needed": bool(getattr(c, "callback_needed", False)),
                "call_attempts": c.call_attempts,
                "last_call_at": c.last_call_at.isoformat() if c.last_call_at else None,
                "call_duration_seconds": c.call_duration_seconds,
                "qualification_score": c.qualification_score,
                "lead_id": str(c.lead_id) if c.lead_id else None,
                "recording_url": c.recording_url,
                "transcript": c.transcript if include_transcript else _snippet(c.transcript),
                "bolna_execution_id": c.bolna_execution_id,
                "analysis": (c.collected_data or {}).get("analysis"),
                "ui_flags": (c.collected_data or {}).get("ui_flags"),
            }
        )

    return success_response(
        message="Calls retrieved",
        data={"items": items, "total": int(total), "page": page, "page_size": page_size},
    )


@router.get("/campaigns/{campaign_id}/calls/{contact_id}")
async def call_detail(
    campaign_id: UUID,
    contact_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Retrieve full details for a single campaign contact, including the complete transcript, collected responses, analytics, and related metadata.
    
    Returns:
        A success response dictionary with `message` "Call detail" and `data` containing the following keys:
        - `id` (str): Contact UUID.
        - `campaign_id` (str): Campaign UUID.
        - `phone` (str | None)
        - `name` (str | None)
        - `pincode` (str | None)
        - `location` (str | None)
        - `status` (str | None)
        - `call_outcome` (str | None)
        - `callback_needed` (bool)
        - `call_attempts` (int | None)
        - `last_call_at` (str | None): ISO 8601 timestamp or `None`.
        - `call_duration_seconds` (int | None)
        - `qualification_score` (float | None)
        - `responses` (dict): Collected responses or empty dict.
        - `collected_data` (dict): Additional collected data or empty dict.
        - `post_call_analytics` (Any | None): Value from `collected_data.post_call_analytics` if present.
        - `lead_id` (str | None)
        - `recording_url` (str | None)
        - `transcript` (str | None)
        - `bolna_execution_id` (str | None)
        - `created_at` (str | None): ISO 8601 timestamp or `None`.
        - `updated_at` (str | None): ISO 8601 timestamp or `None`.
    
    Raises:
        HTTPException: 404 if the contact with the given `contact_id` and `campaign_id` is not found.
    """

    contact = (
        (await db.execute(
            select(CampaignContact).where(
                CampaignContact.id == contact_id,
                CampaignContact.campaign_id == campaign_id,
            )
        ))
        .scalars()
        .first()
    )
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    return success_response(
        message="Call detail",
        data={
            "id": str(contact.id),
            "campaign_id": str(contact.campaign_id),
            "phone": contact.phone,
            "name": contact.name,
            "pincode": contact.pincode,
            "location": contact.location,
            "status": contact.status,
            "call_outcome": contact.call_outcome,
            "callback_needed": bool(getattr(contact, "callback_needed", False)),
            "call_attempts": contact.call_attempts,
            "last_call_at": contact.last_call_at.isoformat() if contact.last_call_at else None,
            "call_duration_seconds": contact.call_duration_seconds,
            "qualification_score": contact.qualification_score,
            "responses": contact.responses or {},
            "collected_data": contact.collected_data or {},
            "post_call_analytics": (contact.collected_data or {}).get("post_call_analytics"),
            "lead_id": str(contact.lead_id) if contact.lead_id else None,
            "recording_url": contact.recording_url,
            "transcript": contact.transcript,
            "bolna_execution_id": contact.bolna_execution_id,
            "created_at": contact.created_at.isoformat() if contact.created_at else None,
            "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
        },
    )


@router.get("/campaigns/{campaign_id}/leads")
async def campaign_leads(
    campaign_id: UUID,
    include_details: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Return the leads created for a campaign, optionally enriched with external lead details.
    
    If `include_details` is true and the current user has a token, the endpoint will attempt a best-effort fetch of lead details from the Lead Ops service for each lead; failures during enrichment do not fail the request and will set `lead_details` to `None`.
    
    Parameters:
        include_details (bool): If true, attempt to fetch and include `lead_details` for each lead when a user token is available.
        limit (int): Maximum number of leads to return (1–200).
    
    Returns:
        dict: A response payload containing:
            - `items` (list): Each item is a dict with keys:
                - `contact_id` (str)
                - `phone` (str | None)
                - `name` (str | None)
                - `lead_id` (str | None)
                - `qualification_score` (float | None)
                - `created_at` (str | None, ISO 8601)
                - `lead_details` (object | None) — present only when `include_details` was requested and a token was available; `None` if enrichment failed.
            - `count` (int): Number of items returned.
    """

    q = (
        select(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.lead_id.is_not(None),
        )
        .order_by(CampaignContact.last_call_at.desc().nullslast(), CampaignContact.created_at.desc())
        .limit(limit)
    )
    contacts = (await db.execute(q)).scalars().all()

    token = current_user.get("token")

    items: list[dict[str, Any]] = []
    for c in contacts:
        row: dict[str, Any] = {
            "contact_id": str(c.id),
            "phone": c.phone,
            "name": c.name,
            "lead_id": str(c.lead_id) if c.lead_id else None,
            "qualification_score": c.qualification_score,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }

        if include_details and token and c.lead_id:
            # Best-effort fetch; do not fail the whole endpoint.
            try:
                details = await lead_ops_client.get_lead_details(UUID(str(c.lead_id)), token)
                row["lead_details"] = details
            except Exception:
                row["lead_details"] = None

        items.append(row)

    return success_response(message="Leads retrieved", data={"items": items, "count": len(items)})
