"""Voice Bot campaign endpoints."""

import json
import uuid
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile
from fastapi import UploadFile as FastapiUploadFile


from app.core.db import get_db
from app.core.auth import get_current_user, require_permission
from app.schemas.voicebot import (
    CampaignCreate,
    CampaignUpdate,
    ContactCreate,
)
from app.services.voicebot_service import VoiceBotService
from shared.responses import success_response, error_response
from shared.error_codes import ErrorCode

from app.services.analytics.sentiment_analysis import (
    analyze_transcript,
    AnalyzeRequest,
    AnalyzeResponse,
    UIFlags,
    DUMMY_TRANSCRIPT,
)


router = APIRouter(prefix="/api/v1/voicebot", tags=["Voice Bot"])


@router.post("/campaigns")
async def create_campaign(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Create a new voice bot campaign.

    Supports:
    - application/json: body is CampaignCreate JSON
    - multipart/form-data:
        - data: CampaignCreate JSON string (required)
        - file: CSV file (optional)
    """
    content_type = (request.headers.get("content-type") or "").lower()

    payload: Any
    upload_file: Optional[UploadFile] = None
    csv_content: Optional[str] = None

    # Parse request
    if "multipart/form-data" in content_type:
        form = await request.form()

        raw_data = form.get("data") or form.get("payload")
        if not raw_data:
            return error_response(
                "Missing form field 'data' (CampaignCreate JSON as string).",
                ErrorCode.VAL_REQUIRED_FIELD,
                details={"expected": "data=<CampaignCreate JSON string>", "optional": "file=<csv>"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = json.loads(str(raw_data))
        except Exception:
            return error_response(
                "Invalid JSON in form field 'data'.",
                ErrorCode.VAL_INVALID_FORMAT,
                details={"field": "data"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        maybe_file = form.get("file")
        if isinstance(maybe_file, (StarletteUploadFile, FastapiUploadFile)):
            upload_file = maybe_file

    else:
        try:
            payload = await request.json()
        except Exception:
            return error_response(
                "Invalid JSON body.",
                ErrorCode.VAL_INVALID_FORMAT,
                details={"content_type": content_type or "unknown"},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    # Validate payload into CampaignCreate
    try:
        data = CampaignCreate.model_validate(payload)
    except ValidationError as e:
        return error_response(
            "Validation error in campaign payload.",
            ErrorCode.VAL_REQUIRED_FIELD,
            details=e.errors(),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # If file provided, validate + decode
    if upload_file is not None:
        if not (upload_file.filename or "").lower().endswith(".csv"):
            return error_response(
                "Only CSV files are accepted.",
                ErrorCode.BULK_INVALID_FILE,
                details={"filename": upload_file.filename},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            content = await upload_file.read()
            csv_content = content.decode("utf-8")
        except Exception:
            return error_response(
                "Unable to read/decode CSV file (expected UTF-8).",
                ErrorCode.BULK_INVALID_FILE,
                details={"filename": upload_file.filename},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    # Create campaign (same logic as before)
    service = VoiceBotService(db)

    campaign = await service.create_campaign(
        name=data.name,
        description=data.description,
        campaign_type=data.campaign_type,
        loan_type=data.loan_type,
        ai_model=data.ai_model,
        voice_gender=data.voice_gender,
        campaign_mode=data.campaign_mode,
        multiple_day=data.multiple_day,
        single_day=data.single_day,
        campaign_start_date=data.campaign_start_date,
        campaign_end_date=data.campaign_end_date,
        campaign_start_time=data.campaign_start_time,
        campaign_end_time=data.campaign_end_time,
        time_mode=data.time_mode,
        selected_days=data.selected_days,
        scheduled_start=data.scheduled_start,
        scheduled_end=data.scheduled_end,
        agent_profile_id=data.agent_profile_id,
        script_config=data.script_config,
        created_by=UUID(current_user["user_id"]) if current_user.get("user_id") else None,
    )

    # Optional: upload contacts during create
    upload_summary: Optional[Dict[str, Any]] = None
    if csv_content is not None:
        total, added, invalid_count, errors = await service.upload_contacts(campaign.id, csv_content)
        upload_summary = {
            "total_rows": total,
            "contacts_added": added,
            "invalid_count": invalid_count,
            "errors": errors[:10] if errors else [],
            "has_more_errors": bool(errors and len(errors) > 10),
        }
    resp = {
        "id": str(campaign.id),
        "name": campaign.name,
        "status": campaign.status,
    }
    if upload_summary is not None:
        resp["contacts_upload"] = upload_summary

    return success_response("Campaign created", resp)



@router.patch("/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: UUID,
    data: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Update fields of an existing voice bot campaign.
    
    Updates the specified campaign with values from `data` and returns the updated campaign identifier and status.
    
    Returns:
        A success response containing the campaign's `id` (string) and `status`.
    
    Raises:
        HTTPException: 404 if the campaign does not exist or cannot be found.
    """
    service = VoiceBotService(db)
    try:
        campaign = await service.update_campaign(
            campaign_id,
            name=data.name,
            description=data.description,
            campaign_type=data.campaign_type,
            loan_type=data.loan_type,
            ai_model=data.ai_model,
            voice_gender=data.voice_gender,
            campaign_mode=data.campaign_mode,
            multiple_day=data.multiple_day,
            single_day=data.single_day,
            campaign_start_date=data.campaign_start_date,
            campaign_end_date=data.campaign_end_date,
            campaign_start_time=data.campaign_start_time,
            campaign_end_time=data.campaign_end_time,
            time_mode=data.time_mode,
            selected_days=data.selected_days,
            scheduled_start=data.scheduled_start,
            scheduled_end=data.scheduled_end,
            agent_profile_id=data.agent_profile_id,
            script_config=data.script_config,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return success_response(
        message="Campaign updated",
        data={"id": str(campaign.id), "status": campaign.status},
    )


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Delete a voice bot campaign and its associated contacts.
    
    Parameters:
        campaign_id (UUID): The ID of the campaign to delete.
    
    Returns:
        dict: Response payload with a confirmation message and `data` containing the deleted campaign's `id` as a string.
    
    Raises:
        HTTPException: 404 if the campaign does not exist.
    """
    service = VoiceBotService(db)
    try:
        await service.delete_campaign(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return success_response(message="Campaign deleted", data={"id": str(campaign_id)})


@router.get("/campaigns")
async def list_campaigns(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Retrieve a paginated list of voice bot campaigns, optionally filtered by status.
    
    Returns:
        A response dictionary whose `data` field contains:
          - `items`: list of campaign summary objects (id, name, status, loan_type, ai_model, voice_gender,
            campaign_mode, scheduled_start, scheduled_end, total_contacts, contacted, qualified,
            leads_created, created_at).
          - `total`: total number of campaigns matching the filter.
          - `page`: current page number.
          - `page_size`: number of items per page.
    """
    service = VoiceBotService(db)
    
    campaigns, total = await service.list_campaigns(
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    
    return success_response(
        message="Campaigns retrieved",
        data={
            "items": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "status": c.status,
                    "loan_type": c.loan_type,
                    "ai_model": c.ai_model,
                    "voice_gender": c.voice_gender,
                    "campaign_mode": c.campaign_mode,
                    "scheduled_start": c.scheduled_start.isoformat() if c.scheduled_start else None,
                    "scheduled_end": c.scheduled_end.isoformat() if c.scheduled_end else None,
                    "total_contacts": c.total_contacts,
                    "contacted": c.contacted,
                    "qualified": c.qualified,
                    "leads_created": c.leads_created,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in campaigns
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/campaigns/{campaign_id}")
async def get_campaign(
    campaign_id: UUID,
    include_contacts: bool = Query(False, alias="include_contacts"),
    contacts_status: Optional[str] = Query(None, alias="contacts_status"),
    contacts_page: int = Query(1, ge=1, alias="contacts_page"),
    contacts_page_size: int = Query(50, ge=1, le=100, alias="contacts_page_size"),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Retrieve detailed information for a voice bot campaign and optionally include its contacts.
    
    Parameters:
    	campaign_id (UUID): Identifier of the campaign to retrieve.
    	include_contacts (bool): If true, include a paginated list of campaign contacts in the response.
    	contacts_status (Optional[str]): Optional status filter to apply when returning contacts.
    	contacts_page (int): Page number to return for contacts paging (1-based).
    	contacts_page_size (int): Number of contacts per page when including contacts.
    
    Returns:
    	response (dict): A success response payload containing campaign fields (id, name, description, schedule, status, counts, script_config, timestamps, etc.). If `include_contacts` is true, includes a `contacts` object with `items` (list of contacts) and pagination metadata (`total`, `page`, `page_size`, `status_filter`).
    """
    service = VoiceBotService(db)

    campaign = await service.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )

    response_data = {
        "id": str(campaign.id),
        "name": campaign.name,
        "description": campaign.description,
        "campaign_type": campaign.campaign_type,
        "loan_type": campaign.loan_type,
        "ai_model": campaign.ai_model,
        "voice_gender": campaign.voice_gender,
        "campaign_mode": campaign.campaign_mode,
        "agent_profile_id": str(campaign.agent_profile_id) if getattr(campaign, "agent_profile_id", None) else None,
        "schedule_config": campaign.schedule_config or {},
        "status": campaign.status,
        "scheduled_start": campaign.scheduled_start.isoformat() if campaign.scheduled_start else None,
        "scheduled_end": campaign.scheduled_end.isoformat() if campaign.scheduled_end else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
        "total_contacts": campaign.total_contacts,
        "contacted": campaign.contacted,
        "qualified": campaign.qualified,
        "disqualified": campaign.disqualified,
        "no_answer": campaign.no_answer,
        "leads_created": campaign.leads_created,
        "script_config": campaign.script_config,
    }

    if include_contacts:
        contacts, total = await service.get_campaign_contacts(
            campaign_id=campaign_id,
            status=contacts_status,
            page=contacts_page,
            page_size=contacts_page_size,
        )

        response_data["contacts"] = {
            "items": [
                {
                    "id": str(c.id),
                    "phone": c.phone,
                    "name": c.name,
                    "status": c.status,
                    "call_attempts": c.call_attempts,
                    "qualification_score": c.qualification_score,
                    "lead_id": str(c.lead_id) if c.lead_id else None,
                }
                for c in contacts
            ],
            "total": total,
            "page": contacts_page,
            "page_size": contacts_page_size,
            "status_filter": contacts_status,
        }

    return success_response(
        message="Campaign retrieved",
        data=response_data,
    )


@router.post("/campaigns/{campaign_id}/contacts")
async def upload_contacts(
    campaign_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Upload a CSV of contacts to the specified campaign.
    
    Expects a UTF-8 encoded CSV where each row is "phone,name" and `name` is optional. The uploaded file must have a .csv extension; otherwise an HTTP 400 is raised.
    
    Parameters:
        campaign_id (UUID): ID of the campaign to receive the contacts.
        file (UploadFile): CSV file to upload. Must have a .csv filename and be UTF-8 decodable.
    
    Returns:
        dict: Summary of the upload containing:
            - total_rows (int): Total rows processed from the CSV.
            - contacts_added (int): Number of contacts successfully added.
            - invalid_count (int): Number of invalid rows.
            - errors (List[str]): Up to 10 error messages describing invalid rows.
            - has_more_errors (bool): True if there are more than 10 errors.
    
    Raises:
        HTTPException: If the uploaded file does not have a .csv extension (400 Bad Request).
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are accepted",
        )
    
    content = await file.read()
    csv_content = content.decode("utf-8")
    
    service = VoiceBotService(db)
    
    total, added, invalid_count, errors = await service.upload_contacts(campaign_id, csv_content)
    
    return success_response(
        message=f"Uploaded {added} contacts",
        data={
            "total_rows": total,
            "contacts_added": added,
            "invalid_count": invalid_count,
            "errors": errors[:10] if errors else [],  # Limit errors shown
            "has_more_errors": len(errors) > 10,
        }
    )


@router.post("/campaigns/{campaign_id}/contacts/manual")
async def add_contact_manually(
    campaign_id: UUID,
    data: ContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Add a single contact to the specified campaign.
    
    Parameters:
        campaign_id (UUID): ID of the campaign to add the contact to.
        data (ContactCreate): Contact fields to create.
    
    Returns:
        dict: Success response containing `data` with the created contact's `id` as a string.
    
    Raises:
        HTTPException: With status 400 if the service rejects the provided data.
    """
    service = VoiceBotService(db)
    try:
        contact = await service.add_contact_manual(campaign_id=campaign_id, **data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return success_response(
        message="Contact added",
        data={"id": str(contact.id)},
    )


@router.get("/campaigns/{campaign_id}/invalid-entries")
async def list_invalid_entries(
    campaign_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Retrieve a paginated list of contacts for a campaign that have invalid phone numbers.
    
    Returns:
    	A success response containing `items` (list of invalid contact records with `id`, `phone`, `name`, `pincode`, `location`, `status`, and `error`) and pagination metadata `total`, `page`, and `page_size`.
    """
    service = VoiceBotService(db)
    contacts, total = await service.get_campaign_contacts(
        campaign_id=campaign_id,
        status="INVALID",
        page=page,
        page_size=page_size,
    )
    return success_response(
        message="Invalid entries retrieved",
        data={
            "items": [
                {
                    "id": str(c.id),
                    "phone": c.phone,
                    "name": c.name,
                    "pincode": c.pincode,
                    "location": c.location,
                    "status": c.status,
                    "error": (c.collected_data or {}).get("error"),
                }
                for c in contacts
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.patch("/campaigns/{campaign_id}/contacts/{contact_id}/resolve")
async def resolve_invalid_entry(
    campaign_id: UUID,
    contact_id: UUID,
    data: ContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Resolve an invalid contact entry by updating its details and marking its status as PENDING.
    
    Parameters:
        campaign_id (UUID): ID of the campaign containing the contact.
        contact_id (UUID): ID of the contact to resolve.
        data (ContactCreate): New contact details to apply.
    
    Returns:
        dict: Success response with `data` containing the resolved contact's `id` (string).
    
    Raises:
        HTTPException: Raised with status 400 when the service rejects the update (validation or business error).
    """
    service = VoiceBotService(db)
    try:
        contact = await service.resolve_contact(
            campaign_id=campaign_id,
            contact_id=contact_id,
            **data.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return success_response(message="Entry resolved", data={"id": str(contact.id)})


@router.delete("/campaigns/{campaign_id}/contacts/{contact_id}")
async def delete_contact(
    campaign_id: UUID,
    contact_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Delete a contact from a campaign by IDs.
    
    Parameters:
        campaign_id (UUID): UUID of the campaign containing the contact.
        contact_id (UUID): UUID of the contact to delete.
    
    Returns:
        dict: Success response containing a message and `data` with the deleted contact `id` as a string.
    
    Raises:
        HTTPException: Raised with status 400 if deletion fails (e.g., invalid IDs or business validation).
    """
    service = VoiceBotService(db)
    try:
        await service.delete_contact(campaign_id=campaign_id, contact_id=contact_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return success_response(message="Contact deleted", data={"id": str(contact_id)})


@router.get("/campaigns/{campaign_id}/contacts")
async def get_campaign_contacts(
    campaign_id: UUID,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.view")),
):
    """
    Retrieve contacts for a campaign, optionally filtered by contact status.
    
    Parameters:
        status_filter (Optional[str]): Contact status to filter by (query alias `status`).
    
    Returns:
        dict: Response payload with:
            - items: list of contact summaries, each containing:
                - id (str): Contact UUID.
                - phone (str): Phone number.
                - name (Optional[str]): Contact name.
                - status (str): Contact status.
                - call_attempts (int): Number of call attempts.
                - qualification_score (Optional[float]): Qualification score.
                - lead_id (Optional[str]): Associated lead UUID or `None`.
            - total (int): Total number of matching contacts.
            - page (int): Current page number.
            - page_size (int): Number of items per page.
    """
    service = VoiceBotService(db)
    
    contacts, total = await service.get_campaign_contacts(
        campaign_id=campaign_id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    
    return success_response(
        message="Contacts retrieved",
        data={
            "items": [
                {
                    "id": str(c.id),
                    "phone": c.phone,
                    "name": c.name,
                    "status": c.status,
                    "call_attempts": c.call_attempts,
                    "qualification_score": c.qualification_score,
                    "lead_id": str(c.lead_id) if c.lead_id else None,
                }
                for c in contacts
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Start a voice bot campaign.
    
    @returns
        A response object containing the campaign `id` (string), `status`, and `started_at` (ISO 8601 timestamp).
    
    @raises HTTPException
        Raised with status 400 when the campaign cannot be started (e.g., invalid state); the exception detail contains the error message.
    """
    service = VoiceBotService(db)
    
    try:
        campaign = await service.start_campaign(campaign_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    return success_response(
        message="Campaign started",
        data={
            "id": str(campaign.id),
            "status": campaign.status,
            "started_at": campaign.started_at.isoformat(),
        }
    )


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Pause an active voice bot campaign.
    
    Returns:
        A success response containing the campaign's `id` and updated `status`.
    """
    service = VoiceBotService(db)
    try:
        campaign = await service.pause_campaign(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return success_response(
        message="Campaign paused",
        data={"id": str(campaign.id), "status": campaign.status},
    )


@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Dict = Depends(require_permission("voicebot.manage")),
):
    """
    Stop a voice campaign.
    
    Raises:
        HTTPException: If the campaign cannot be stopped (returns 400 Bad Request).
    
    Returns:
        dict: Success response containing the campaign `id` and `status`.
    """
    service = VoiceBotService(db)
    try:
        campaign = await service.stop_campaign(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return success_response(
        message="Campaign stopped",
        data={"id": str(campaign.id), "status": campaign.status},
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def post_call_analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    """
    Analyze a call transcript and produce structured analysis with UI flags.
    
    Parameters:
        payload (AnalyzeRequest): Contains `transcript` (the call text to analyze) and `call_id` (identifier for the call).
    
    Returns:
        AnalyzeResponse: Response containing `call_id`, the analysis result, and `ui_flags` (including `show_callback_button` set when the analysis indicates a callback was requested).
    """
    result = analyze_transcript(payload.transcript)
    return AnalyzeResponse(
        call_id=payload.call_id,
        analysis=result,
        ui_flags=UIFlags(show_callback_button=result.callback_requested),
    )

