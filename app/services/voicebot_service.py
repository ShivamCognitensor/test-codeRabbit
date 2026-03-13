"""
Voice Bot Service - Campaign-driven lead generation with Bolna.ai integration.

Features:
- Campaign management (create, start, pause, stop)
- Contact CSV upload and processing
- Bolna.ai integration for automated calling
- Call result processing and lead creation
"""

import csv
import io
import logging
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import asc, select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import VoiceBotCampaign, CampaignContact
from app.clients.bolna_client import bolna_client
from app.core.config import settings

logger = logging.getLogger(__name__)


class VoiceBotService:
    # -----------------------------
    # Normalizers / parsers
    # -----------------------------

    @staticmethod
    def _normalize_phone(phone: str) -> Optional[str]:
        if not phone:
            return None
        digits = "".join(c for c in str(phone) if c.isdigit())
        if len(digits) < 10:
            return None
        return digits[-10:]

    @staticmethod
    def _parse_time_str(val: Optional[str]) -> Optional[time]:
        """Parse '09:00 am', '9:00 AM', '18:30' etc into a time object."""
        if not val:
            return None
        s = str(val).strip()
        if not s:
            return None

        # try a few common formats
        candidates = [
            "%I:%M %p",
            "%I:%M%p",
            "%I %p",
            "%H:%M",
            "%H:%M:%S",
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(s, fmt).time()
            except ValueError:
                continue
        return None

    @classmethod
    def _combine_date_time(cls, d: Optional[date], t: Optional[str]) -> Optional[datetime]:
        if not d:
            return None
        parsed_t = cls._parse_time_str(t)
        if parsed_t is None:
            return datetime.combine(d, time(0, 0))
        return datetime.combine(d, parsed_t)

    """Service for voice bot campaign management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_campaign(
        self,
        name: str,
        description: Optional[str] = None,
        campaign_type: Optional[str] = None,
        loan_type: Optional[str] = None,
        ai_model: Optional[str] = None,
        voice_gender: Optional[str] = None,
        campaign_mode: Optional[str] = None,
        # schedule (UI)
        multiple_day: Optional[bool] = None,
        single_day: Optional[bool] = None,
        campaign_start_date: Optional[date] = None,
        campaign_end_date: Optional[date] = None,
        campaign_start_time: Optional[str] = None,
        campaign_end_time: Optional[str] = None,
        time_mode: Optional[str] = None,
        selected_days: Optional[List[str]] = None,
        # derived schedule (back-compat)
        scheduled_start: Optional[datetime] = None,
        scheduled_end: Optional[datetime] = None,
        # script/assistant
        agent_profile_id: Optional[UUID] = None,
        script_config: Optional[Dict] = None,
        created_by: Optional[UUID] = None,
    ) -> VoiceBotCampaign:
        """Create a new voice bot campaign."""

        # Derive schedule range if UI fields are provided
        if not scheduled_start and campaign_start_date:
            scheduled_start = self._combine_date_time(campaign_start_date, campaign_start_time)
        if not scheduled_end and campaign_end_date:
            scheduled_end = self._combine_date_time(campaign_end_date, campaign_end_time)

        schedule_config: Dict[str, Any] = {
            "multipleDay": bool(multiple_day) if multiple_day is not None else None,
            "singleDay": bool(single_day) if single_day is not None else None,
            "campaignStartDate": campaign_start_date.isoformat() if campaign_start_date else None,
            "campaignEndDate": campaign_end_date.isoformat() if campaign_end_date else None,
            "campaignStartTime": campaign_start_time,
            "campaignEndTime": campaign_end_time,
            "timeMode": time_mode,
            "selectedDays": selected_days or [],
        }

        campaign = VoiceBotCampaign(
            name=name,
            description=description,
            campaign_type=campaign_type,
            loan_type=loan_type,
            ai_model=ai_model,
            voice_gender=voice_gender,
            campaign_mode=campaign_mode,
            schedule_config=schedule_config,
            agent_profile_id=agent_profile_id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            script_config=script_config or {},
            status="DRAFT",
            created_by=created_by,
        )
        
        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)
        
        return campaign

    async def update_campaign(self, campaign_id: UUID, **fields: Any) -> VoiceBotCampaign:
        """Patch campaign fields (used by the multi-step wizard)."""
        campaign = await self.db.get(VoiceBotCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaign not found")

        # Update simple scalar fields
        for key in [
            "name",
            "description",
            "campaign_type",
            "loan_type",
            "ai_model",
            "voice_gender",
            "campaign_mode",
            "agent_profile_id",
        ]:
            if key in fields and fields[key] is not None:
                setattr(campaign, key, fields[key])

        # Schedule fields: merge into schedule_config and (re)compute scheduled_start/end
        schedule_keys = {
            "multiple_day": "multipleDay",
            "single_day": "singleDay",
            "campaign_start_date": "campaignStartDate",
            "campaign_end_date": "campaignEndDate",
            "campaign_start_time": "campaignStartTime",
            "campaign_end_time": "campaignEndTime",
            "time_mode": "timeMode",
            "selected_days": "selectedDays",
        }
        if campaign.schedule_config is None:
            campaign.schedule_config = {}

        for src, dst in schedule_keys.items():
            if src in fields and fields[src] is not None:
                val = fields[src]
                if isinstance(val, date):
                    val = val.isoformat()
                campaign.schedule_config[dst] = val

        # If explicit scheduled_start/end provided, keep them.
        if fields.get("scheduled_start") is not None:
            campaign.scheduled_start = fields["scheduled_start"]
        if fields.get("scheduled_end") is not None:
            campaign.scheduled_end = fields["scheduled_end"]

        # Otherwise, try to derive from schedule_config
        if fields.get("scheduled_start") is None and fields.get("campaign_start_date") is not None:
            campaign.scheduled_start = self._combine_date_time(fields.get("campaign_start_date"), fields.get("campaign_start_time"))
        if fields.get("scheduled_end") is None and fields.get("campaign_end_date") is not None:
            campaign.scheduled_end = self._combine_date_time(fields.get("campaign_end_date"), fields.get("campaign_end_time"))

        # Script config
        if fields.get("script_config") is not None:
            campaign.script_config = fields.get("script_config") or {}

        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def delete_campaign(self, campaign_id: UUID) -> None:
        """Delete a campaign and its contacts (Campaign Remove in the UI)."""
        campaign = await self.db.get(VoiceBotCampaign, campaign_id)
        if not campaign:
            raise ValueError("Campaign not found")

        # Delete contacts first to avoid FK constraints
        await self.db.execute(
            delete(CampaignContact).where(CampaignContact.campaign_id == campaign_id)
        )
        await self.db.delete(campaign)
        await self.db.commit()
    
    async def upload_contacts(
        self,
        campaign_id: UUID,
        csv_content: str,
    ) -> Tuple[int, int, int, List[str]]:
        """
        Upload contacts from CSV to a campaign.
        
        CSV format: phone,name (name is optional)
        
        Returns:
            Tuple of (total_rows, added_contacts, invalid_count, errors)
        """
        # Get campaign
        result = await self.db.execute(
            select(VoiceBotCampaign).where(VoiceBotCampaign.id == campaign_id)
        )
        campaign = result.scalars().first()
        
        if not campaign:
            return 0, 0, 0, ["Campaign not found"]
        
        if campaign.status not in ["DRAFT", "SCHEDULED"]:
            return 0, 0, 0, ["Cannot add contacts to campaign in current status"]
        
        # Parse CSV
        errors: List[str] = []
        added = 0
        invalid_count = 0
        total = 0
        
        try:
            reader = csv.DictReader(io.StringIO(csv_content))

            def _get(row: Dict[str, Any], *candidates: str) -> str:
                # Case-insensitive lookup across possible column names.
                lowered = {str(k).strip().lower(): k for k in row.keys()}
                for cand in candidates:
                    key = str(cand).strip().lower()
                    if key in lowered:
                        return str(row.get(lowered[key]) or "").strip()
                return ""
            
            for row in reader:
                total += 1
                
                if total > settings.MAX_CAMPAIGN_CONTACTS:
                    errors.append(f"Maximum {settings.MAX_CAMPAIGN_CONTACTS} contacts allowed")
                    break
                
                phone_raw = _get(row, "phone", "phone_number", "phone number", "mobile", "mob", "mob number")
                name = _get(row, "name", "customer_name", "customer name")
                pincode = _get(row, "pincode", "pin", "zip")
                location = _get(row, "location", "city", "state")
                
                if not phone_raw:
                    errors.append(f"Row {total}: Missing phone number")
                    continue

                phone = self._normalize_phone(phone_raw)
                if not phone:
                    # UI shows these as "Incorrect Entry".
                    invalid = CampaignContact(
                        campaign_id=campaign_id,
                        phone=str(phone_raw)[:15],
                        name=name or None,
                        pincode=pincode or None,
                        location=location or None,
                        status="INVALID",
                        call_outcome="INCORRECT_ENTRY",
                        collected_data={"error": "Invalid phone number", "raw": phone_raw},
                    )
                    self.db.add(invalid)
                    added += 1
                    invalid_count += 1
                    continue
                
                # Create contact
                contact = CampaignContact(
                    campaign_id=campaign_id,
                    phone=phone,
                    name=name or None,
                    pincode=pincode or None,
                    location=location or None,
                    status="PENDING",
                    call_outcome="NOT_CONNECT",
                )
                self.db.add(contact)
                added += 1
        
        except Exception as e:
            errors.append(f"CSV parsing error: {str(e)}")
            return total, added, invalid_count, errors
        
        # Update campaign contact count
        campaign.total_contacts = (campaign.total_contacts or 0) + added
        
        await self.db.commit()
        
        return total, added, invalid_count, errors
    
    async def start_campaign(self, campaign_id: UUID) -> VoiceBotCampaign:
        """Start a campaign."""
        result = await self.db.execute(
            select(VoiceBotCampaign).where(VoiceBotCampaign.id == campaign_id)
        )
        campaign = result.scalars().first()
        
        if not campaign:
            raise ValueError("Campaign not found")
        
        if campaign.status not in ["DRAFT", "SCHEDULED", "PAUSED"]:
            raise ValueError(f"Cannot start campaign in {campaign.status} status")
        
        if campaign.total_contacts == 0:
            raise ValueError("Campaign has no contacts")
        
        campaign.status = "RUNNING"
        campaign.started_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(campaign)
        
        # Trigger Bolna calls based on campaign mode
        if bolna_client.is_enabled:
            await self._trigger_bolna_campaign(campaign)
        else:
            logger.info(f"Bolna not configured - campaign {campaign_id} started in stub mode")
        
        return campaign
    
    async def _trigger_bolna_campaign(self, campaign: VoiceBotCampaign) -> None:
        """
        Trigger Bolna calls for a campaign in sequential mode:
        - Only ONE contact can be IN_PROGRESS at a time.
        - If one is already IN_PROGRESS, do nothing.
        - Otherwise, pick the oldest PENDING and start call.
        """

        # 1) If any call is already in progress for this campaign, don't start another.
        in_progress_count = (
            await self.db.execute(
                select(func.count())
                .select_from(CampaignContact)
                .where(
                    CampaignContact.campaign_id == campaign.id,
                    CampaignContact.status == "IN_PROGRESS",
                )
            )
        ).scalar() or 0

        if in_progress_count > 0:
            logger.info("Campaign %s: call already IN_PROGRESS, skipping trigger.", campaign.id)
            return

        # 2) Pick next pending contact (oldest first for CSV order)
        result = await self.db.execute(
            select(CampaignContact)
            .where(
                CampaignContact.campaign_id == campaign.id,
                CampaignContact.status == "PENDING",
            )
            .order_by(asc(CampaignContact.created_at))  # ensures top of CSV goes first
            .limit(1)
        )
        contact = result.scalars().first()

        if not contact:
            logger.info("Campaign %s: no PENDING contacts left.", campaign.id)
            return

        await self._make_bolna_call(contact, campaign)


    async def _make_bolna_call(
        self,
        contact: CampaignContact,
        campaign: VoiceBotCampaign,
    ) -> Optional[str]:
        """Make a single Bolna call for a contact."""

        # Build context for the call
        context: Dict[str, Any] = {
            "contact_name": contact.name or "Customer",
            "contact_phone": contact.phone,
            "campaign_name": campaign.name,
        }

        # Add any script config
        if campaign.script_config:
            context.update(campaign.script_config)

        # Format phone number (E.164) default India
        phone = (contact.phone or "").strip()
        if phone.isdigit() and len(phone) == 10:
            phone = f"+91{phone}"
        elif phone and not phone.startswith("+"):
            phone = f"+{phone}"

        # If phone is still invalid, mark failed
        if not phone or len(phone) < 8:
            contact.status = "FAILED"
            contact.call_attempts = (contact.call_attempts or 0) + 1
            await self.db.commit()
            logger.error("Invalid phone for contact %s: %s", contact.id, contact.phone)
            return None

        try:
            result = await bolna_client.make_call(
                to_phone=phone,
                agent_id=campaign.bolna_agent_id or settings.BOLNA_DEFAULT_AGENT_ID,
                context=context,
            )
        except Exception:
            # network/bolna error
            logger.exception("Bolna call exception for contact %s", contact.id)
            contact.status = "FAILED"
            contact.call_attempts = (contact.call_attempts or 0) + 1
            await self.db.commit()
            return None

        if result:
            exec_id = (result.get("execution_id") or result.get("id") or "").strip()

            contact.status = "IN_PROGRESS"
            contact.bolna_execution_id = exec_id or contact.bolna_execution_id
            contact.last_call_at = datetime.utcnow()
            contact.call_attempts = (contact.call_attempts or 0) + 1

            await self.db.commit()

            logger.info("Bolna call initiated: contact=%s exec_id=%s", contact.id, exec_id)
            return exec_id

        # If Bolna returned empty/false
        contact.status = "FAILED"
        contact.call_attempts = (contact.call_attempts or 0) + 1
        await self.db.commit()

        logger.error("Failed to initiate Bolna call for contact %s", contact.id)
        return None
    
    async def pause_campaign(self, campaign_id: UUID) -> VoiceBotCampaign:
        """Pause a running campaign."""
        result = await self.db.execute(
            select(VoiceBotCampaign).where(VoiceBotCampaign.id == campaign_id)
        )
        campaign = result.scalars().first()
        
        if not campaign:
            raise ValueError("Campaign not found")
        
        if campaign.status != "RUNNING":
            raise ValueError(f"Cannot pause campaign in {campaign.status} status")
        
        campaign.status = "PAUSED"
        await self.db.commit()
        await self.db.refresh(campaign)
        
        logger.info(f"Campaign {campaign_id} paused")
        return campaign
    
    async def stop_campaign(self, campaign_id: UUID) -> VoiceBotCampaign:
        """Stop a campaign (cannot be resumed)."""
        result = await self.db.execute(
            select(VoiceBotCampaign).where(VoiceBotCampaign.id == campaign_id)
        )
        campaign = result.scalars().first()
        
        if not campaign:
            raise ValueError("Campaign not found")
        
        if campaign.status == "COMPLETED":
            raise ValueError("Campaign is already completed")
        
        campaign.status = "STOPPED"
        campaign.completed_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(campaign)
        
        logger.info(f"Campaign {campaign_id} stopped")
        return campaign
    
    async def process_call_result(
        self,
        contact_id: UUID,
        status: str,
        call_duration: Optional[int] = None,
        responses: Optional[Dict] = None,
        qualification_score: Optional[int] = None,
        collected_data: Optional[Dict] = None,
    ) -> CampaignContact:
        result = await self.db.execute(
            select(CampaignContact).where(CampaignContact.id == contact_id)
        )
        contact = result.scalars().first()

        if not contact:
            raise ValueError("Contact not found")

        prev_status = contact.status  #  track for idempotency

        #  Update contact
        contact.status = status

        # Keep a UI-friendly outcome token for the dashboard (matches Figma labels)
        if status == "IN_PROGRESS":
            contact.call_outcome = "ONGOING_CALL"
        elif status in ("QUALIFIED", "DISQUALIFIED", "CONTACTED"):
            contact.call_outcome = "ANSWERED_CALL"
        elif status == "NO_ANSWER":
            contact.call_outcome = "NO_ANSWER_CALL"
        elif status == "FAILED":
            contact.call_outcome = "NOT_CONNECT"
        elif status == "INVALID":
            contact.call_outcome = "INCORRECT_ENTRY"
        # REMOVE this line (attempt already incremented when call initiated)
        # contact.call_attempts += 1

        contact.last_call_at = datetime.utcnow()
        if call_duration is not None:
            contact.call_duration_seconds = call_duration

        contact.responses = responses or {}

        if qualification_score is not None:
            contact.qualification_score = qualification_score

        # MERGE collected_data instead of overwriting
        contact.collected_data = {**(contact.collected_data or {}), **(collected_data or {})}

        # Best-effort callback flag
        try:
            cd = contact.collected_data or {}
            if isinstance(cd, dict):
                na = cd.get("next_action")
                if na and "call" in str(na).lower() and "back" in str(na).lower():
                    contact.callback_needed = True
                    contact.call_outcome = "CALLBACK_NEED"
        except Exception:
            pass

        await self.db.commit()

        # Update campaign stats ONLY if status actually changed to a final state
        campaign_result = await self.db.execute(
            select(VoiceBotCampaign).where(VoiceBotCampaign.id == contact.campaign_id)
        )
        campaign = campaign_result.scalars().first()

        if campaign:
            # prevent double counting (duplicate "completed" webhooks)
            if prev_status != status and status in ("QUALIFIED", "DISQUALIFIED", "NO_ANSWER", "CONTACTED"):
                campaign.contacted = (campaign.contacted or 0) + 1

                if status == "QUALIFIED":
                    campaign.qualified = (campaign.qualified or 0) + 1

                    # Create lead only once
                    if not contact.lead_id:
                        lead_id = await self._create_lead_from_contact(contact)
                        if lead_id:
                            contact.lead_id = lead_id
                            campaign.leads_created = (campaign.leads_created or 0) + 1

                elif status == "DISQUALIFIED":
                    campaign.disqualified = (campaign.disqualified or 0) + 1

                elif status == "NO_ANSWER":
                    campaign.no_answer = (campaign.no_answer or 0) + 1

                await self.db.commit()

        await self.db.refresh(contact)
        return contact
    
    async def _create_lead_from_contact(
        self,
        contact: CampaignContact,
    ) -> Optional[UUID]:
        """Create a lead from a qualified voice bot contact."""
        from app.clients.lead_ops_client import lead_ops_client

        payload = {
            "borrower_phone": contact.phone,
            "borrower_name": contact.name,
            "source": "VOICEBOT",
            "loan_type_code": (contact.collected_data or {}).get("loan_type") or "PERSONAL",
            "requested_amount": (contact.collected_data or {}).get("amount") or (contact.collected_data or {}).get("loan_amount"),
            "metadata": {
                "campaign_contact_id": str(contact.id),
                "campaign_id": str(contact.campaign_id),
                "qualification_score": contact.qualification_score,
                "collected_data": contact.collected_data or {},
            },
        }

        try:
            data = await lead_ops_client.create_lead_internal(payload)
            if not data:
                return None

            # Common shapes: {id: ...} or {lead_id: ...} or {data:{id:...}}
            lead_id_val = data.get("id") or data.get("lead_id") or data.get("leadId")
            if not lead_id_val and isinstance(data.get("data"), dict):
                lead_id_val = data["data"].get("id") or data["data"].get("lead_id")

            return UUID(str(lead_id_val)) if lead_id_val else None
        except Exception:
            logger.exception("Error creating lead from voice bot contact")
            return None

    async def run_post_call_analytics(self, contact: CampaignContact, transcript: str) -> Dict[str, Any]:
        """Generate and store post-call analytics used by the dashboard.

        Stored at: contact.collected_data["post_call_analytics"]
        """
        from app.services.analytics.post_call import extract_post_call_analytics

        # Use campaign.ai_model as default if present; allow overrides via script_config
        campaign = await self.get_campaign(contact.campaign_id)
        provider = None
        model = None
        schema = None
        if campaign and isinstance(campaign.script_config, dict):
            analytics_cfg = campaign.script_config.get("post_call_analytics") or {}
            if isinstance(analytics_cfg, dict):
                provider = analytics_cfg.get("provider")
                model = analytics_cfg.get("model")
                schema = analytics_cfg.get("schema")

        model = model or (campaign.ai_model if campaign and campaign.ai_model else None)

        analytics = await extract_post_call_analytics(transcript=transcript, schema=schema, provider=provider, model=model)

        if not contact.collected_data or not isinstance(contact.collected_data, dict):
            contact.collected_data = {}
        contact.collected_data["post_call_analytics"] = analytics

        # Optionally sync a few top-level fields
        try:
            if isinstance(analytics, dict):
                if "qualification_score" in analytics and isinstance(analytics.get("qualification_score"), int):
                    contact.qualification_score = analytics["qualification_score"]
                if "qualified" in analytics and isinstance(analytics.get("qualified"), bool):
                    # If transcript suggests callback needed, we keep callback flag
                    contact.callback_needed = bool(analytics.get("next_action") and "call" in str(analytics.get("next_action")).lower())
        except Exception:
            pass

        await self.db.commit()
        await self.db.refresh(contact)
        return analytics
    
    async def get_campaign(self, campaign_id: UUID) -> Optional[VoiceBotCampaign]:
        """Get a campaign by ID."""
        result = await self.db.execute(
            select(VoiceBotCampaign).where(VoiceBotCampaign.id == campaign_id)
        )
        return result.scalars().first()
    
    async def list_campaigns(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[VoiceBotCampaign], int]:
        """List campaigns with optional status filter."""
        query = select(VoiceBotCampaign)
        
        if status:
            query = query.where(VoiceBotCampaign.status == status)
        
        # Count
        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()
        
        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(VoiceBotCampaign.created_at.desc()).offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        campaigns = list(result.scalars().all())
        
        return campaigns, total
    
    async def get_campaign_contacts(
        self,
        campaign_id: UUID,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[CampaignContact], int]:
        """Get contacts for a campaign."""
        query = select(CampaignContact).where(CampaignContact.campaign_id == campaign_id)
        
        if status:
            query = query.where(CampaignContact.status == status)
        
        # Count
        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar()
        
        # Paginate
        offset = (page - 1) * page_size
        query = query.order_by(CampaignContact.created_at.desc()).offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        contacts = list(result.scalars().all())
        
        return contacts, total

    async def add_contact_manual(
        self,
        campaign_id: UUID,
        phone: str,
        name: Optional[str] = None,
        pincode: Optional[str] = None,
        location: Optional[str] = None,
    ) -> CampaignContact:
        """Add a single contact from the dashboard UI."""
        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            raise ValueError("Campaign not found")
        if campaign.status not in ["DRAFT", "SCHEDULED"]:
            raise ValueError("Cannot add contacts to campaign in current status")

        normalized = self._normalize_phone(phone)
        if not normalized:
            # Store as invalid entry (matches the UI 'Incorrect Entry').
            contact = CampaignContact(
                campaign_id=campaign_id,
                phone=str(phone)[:15],
                name=name or None,
                pincode=pincode or None,
                location=location or None,
                status="INVALID",
                call_outcome="INCORRECT_ENTRY",
                collected_data={"error": "Invalid phone number", "raw": phone},
            )
        else:
            contact = CampaignContact(
                campaign_id=campaign_id,
                phone=normalized,
                name=name or None,
                pincode=pincode or None,
                location=location or None,
                status="PENDING",
                call_outcome="NOT_CONNECT",
            )

        self.db.add(contact)
        campaign.total_contacts = (campaign.total_contacts or 0) + 1
        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def resolve_contact(
        self,
        campaign_id: UUID,
        contact_id: UUID,
        phone: str,
        name: Optional[str] = None,
        pincode: Optional[str] = None,
        location: Optional[str] = None,
    ) -> CampaignContact:
        """Resolve an invalid entry by updating it back to a valid pending contact."""
        contact = await self.db.get(CampaignContact, contact_id)
        if not contact or contact.campaign_id != campaign_id:
            raise ValueError("Contact not found")

        normalized = self._normalize_phone(phone)
        if not normalized:
            raise ValueError("Invalid phone number")

        contact.phone = normalized
        contact.name = name or None
        contact.pincode = pincode or None
        contact.location = location or None
        contact.status = "PENDING"
        contact.call_outcome = "NOT_CONNECT"
        if contact.collected_data and isinstance(contact.collected_data, dict):
            contact.collected_data.pop("error", None)
            contact.collected_data.pop("raw", None)

        await self.db.commit()
        await self.db.refresh(contact)
        return contact

    async def delete_contact(self, campaign_id: UUID, contact_id: UUID) -> None:
        """Delete a contact and keep campaign counters roughly consistent."""
        contact = await self.db.get(CampaignContact, contact_id)
        if not contact or contact.campaign_id != campaign_id:
            raise ValueError("Contact not found")

        campaign = await self.get_campaign(campaign_id)
        await self.db.delete(contact)
        if campaign:
            campaign.total_contacts = max(int(campaign.total_contacts or 0) - 1, 0)
        await self.db.commit()
