from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from zoneinfo import ZoneInfo

from app.clients.bolna_client import BolnaClient
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import async_session_maker
from app.models.crm_models import LeadCRM
from app.models.voicefin_models import (
    CampaignMode,
    CampaignStatus,
    LeadCallState,
    VoicefinCampaign,
    VoicefinCampaignLead,
    VoicefinEvent,
    VoicefinEventType,
    VoicefinLeadContact,
)


logger = get_logger(__name__)


def _parse_hhmm(value: str | None) -> dtime | None:
    """
    Parse an "HH:MM" formatted string into a time object.
    
    Parameters:
        value (str | None): A string with hour and minute separated by ":", e.g. "09:30". Leading/trailing whitespace is allowed.
    
    Returns:
        datetime.time | None: A time object with the parsed hour and minute, or `None` if `value` is falsy or not a valid "HH:MM" string.
    """
    if not value:
        return None
    try:
        hh, mm = value.strip().split(":")
        return dtime(hour=int(hh), minute=int(mm))
    except Exception:
        return None


def _within_window(now: datetime, start: dtime | None, end: dtime | None) -> bool:
    """
    Check whether the time component of `now` falls inside the daily window defined by `start` and `end`.
    
    Parameters:
        now (datetime): Reference datetime whose time component is checked.
        start (time | None): Window start time; if `None` the window constraint is disabled.
        end (time | None): Window end time; if `None` the window constraint is disabled.
    
    Returns:
        `true` if `now.time()` is within the inclusive window [start, end] (or if either `start` or `end` is `None`), `false` otherwise.
    """
    if not start or not end:
        return True
    t = now.time()
    if start <= end:
        return start <= t <= end
    # window spans midnight
    return t >= start or t <= end


@dataclass
class CampaignRunner:
    """Background scheduler for SEQUENTIAL campaigns."""

    scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        """
        Start the campaign runner scheduler.
        
        Initializes and starts a background AsyncIOScheduler that invokes self._tick at the interval configured by settings.campaign_tick_seconds. If a scheduler is already running, the method is a no-op. The scheduled job is configured to allow only one concurrent instance of the tick, and the start is logged.
        """
        s = get_settings()
        if self.scheduler and self.scheduler.running:
            return
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(self._tick, "interval", seconds=s.campaign_tick_seconds, max_instances=1)
        self.scheduler.start()
        logger.info("campaign_runner_started", tick_seconds=s.campaign_tick_seconds)

    def shutdown(self) -> None:
        """
        Stop the scheduler if it is currently running.
        
        If a scheduler instance exists and is running, shuts it down without waiting and logs the stop event; otherwise does nothing.
        """
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("campaign_runner_stopped")

    async def _tick(self) -> None:
        """
        Run one scheduler tick that processes all running sequential campaigns.
        
        Finds VoicefinCampaign records with status RUNNING and mode SEQUENTIAL, invokes _run_campaign_tick for each, and commits any database changes. Exceptions raised during the tick are caught and logged; the method does not propagate them.
        """
        s = get_settings()
        try:
            async with async_session_maker() as db:
                res = await db.execute(
                    select(VoicefinCampaign)
                    .where(VoicefinCampaign.status == CampaignStatus.RUNNING)
                    .where(VoicefinCampaign.mode == CampaignMode.SEQUENTIAL)
                )
                campaigns = res.scalars().all()
                for camp in campaigns:
                    await self._run_campaign_tick(db, camp)
                await db.commit()
        except Exception:
            logger.exception("campaign_runner_tick_failed")

    async def _run_campaign_tick(self, db, camp: VoicefinCampaign) -> None:
        """
        Process a single campaign tick: select due pending leads for the campaign, attempt to dispatch calls for them, update lead states and record events, and mark the campaign completed when no pending leads remain.
        
        This enforces the campaign's call window and rate limits, selects up to the per-tick number of pending leads ordered by sequence, and uses the Bolna client to place calls. For each dispatched lead it updates execution identifiers, attempts, timestamps, and call state; on dispatch failure it marks the lead as failed and records the error. If no pending leads are found the campaign status is set to COMPLETED and a CAMPAIGN_STOPPED event is created.
        
        Parameters:
            db: Asynchronous database session used to query and persist campaign, lead, contact, and event records.
            camp (VoicefinCampaign): The campaign being processed; its timezone, call window, calls-per-minute, agent/from phone overrides, and status are used to control behavior.
        """
        s = get_settings()
        tz = ZoneInfo(camp.timezone or s.campaign_default_timezone)
        now = datetime.now(tz)

        start = _parse_hhmm(camp.call_window_start)
        end = _parse_hhmm(camp.call_window_end)
        if not _within_window(now, start, end):
            return

        rpm = int(camp.calls_per_minute or s.campaign_default_calls_per_minute)
        tick_seconds = max(1, int(s.campaign_tick_seconds))
        per_tick = max(1, int(round(rpm * tick_seconds / 60.0)))

        agent_id = camp.bolna_agent_id or s.bolna_default_agent_id
        if not agent_id:
            return
        from_number = camp.bolna_from_phone_number or s.bolna_default_from_phone_number

        # next leads
        q = (
            select(VoicefinCampaignLead)
            .where(VoicefinCampaignLead.campaign_id == camp.id)
            .where(VoicefinCampaignLead.is_active.is_(True))
            .where(VoicefinCampaignLead.call_state.in_([LeadCallState.PENDING]))
            .order_by(VoicefinCampaignLead.sequence.asc())
            .limit(per_tick)
        )
        res = await db.execute(q)
        leads = res.scalars().all()
        if not leads:
            # campaign completed
            camp.status = CampaignStatus.COMPLETED
            camp.completed_at = datetime.utcnow()
            db.add(
                VoicefinEvent(
                    event_type=VoicefinEventType.CAMPAIGN_STOPPED,
                    message=f"Campaign completed: {camp.name}",
                    campaign_id=camp.id,
                )
            )
            return

        bolna = BolnaClient.from_settings()

        for cl in leads:
            # fetch CRM lead phone
            res2 = await db.execute(select(LeadCRM).where(LeadCRM.lead_id == cl.lead_id))
            lead = res2.scalar_one_or_none()
            if not lead:
                cl.call_state = LeadCallState.FAILED
                cl.last_error = "LeadCRM not found"
                continue

            # optional contact meta
            res3 = await db.execute(select(VoicefinLeadContact).where(VoicefinLeadContact.lead_id == cl.lead_id))
            contact = res3.scalar_one_or_none()

            user_data: dict[str, Any] = {
                "lead_id": str(cl.lead_id),
                "campaign_id": str(camp.id),
            }
            # if contact and contact.name:
            #     user_data["name"] = contact.name
            if contact and contact.pincode:
                user_data["pincode"] = contact.pincode

            user_data.update({
                "agent_name": "Poonam",          # better: read from env/settings
                "brand_name": "Roinet",
                "customer_name": contact.name if contact else "",
                "morning_or_afternoon": "morning",   # or compute from time
                "rate_starting_from": "9.9"
                })

            try:
                resp = await bolna.make_call(
                    agent_id=agent_id,
                    recipient_phone_number=str(lead.phone_number),
                    from_phone_number=from_number,
                    user_data=user_data,
                )
                execution_id = resp.get("execution_id") or resp.get("id") or resp.get("call_id")
                cl.execution_id = str(execution_id) if execution_id else None
                cl.call_state = LeadCallState.QUEUED
                cl.attempts = int(cl.attempts or 0) + 1
                cl.last_called_at = datetime.utcnow()
                db.add(
                    VoicefinEvent(
                        event_type=VoicefinEventType.WEBHOOK_RECEIVED,
                        message=f"Call queued via Bolna (execution_id={execution_id})",
                        campaign_id=camp.id,
                        lead_id=cl.lead_id,
                    )
                )
            except Exception as e:
                cl.call_state = LeadCallState.FAILED
                cl.attempts = int(cl.attempts or 0) + 1
                cl.last_error = str(e)
                db.add(
                    VoicefinEvent(
                        event_type=VoicefinEventType.WEBHOOK_RECEIVED,
                        message=f"Call dispatch failed: {e}",
                        campaign_id=camp.id,
                        lead_id=cl.lead_id,
                    )
                )


campaign_runner = CampaignRunner()
