from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openai_client import get_openai_client
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.analytics_models import CallAnalytics
from app.models.crm_models import LeadCRM
from app.models.enums import CallStatus
from app.models.voicefin_models import VoicefinCampaignLead


logger = get_logger(__name__)


_ANALYSIS_SYSTEM = (
    "You are an expert Indian loan sales QA analyst. "
    "Given a transcript of a phone call about personal loan lead qualification, "
    "extract key details and return STRICT JSON only (no markdown)."
)


_ANALYSIS_USER_TEMPLATE = """Transcript:\n{transcript}\n\nReturn JSON with keys:\n- interested: true/false/unknown\n- city: string|null\n- pincode: string|null\n- employment_type: salaried/self-employed/unknown\n- monthly_income: string|null\n- loan_amount: string|null\n- existing_emi: string|null\n- purpose: string|null\n- timeline: string|null\n- credit_band: good/average/unknown\n- sentiment: positive/neutral/negative\n- outcome: QUALIFIED/REJECTED/CALLBACK_NEEDED\n- summary: 1-2 lines\n"""


@dataclass
class CallAnalysisService:
    db: AsyncSession

    def __post_init__(self) -> None:
        """
        Initialize instance configuration and OpenAI client.
        
        Sets instance attributes `s` (settings) and `client` (OpenAI client) for use by other methods.
        """
        self.s = get_settings()
        self.client = get_openai_client()

    async def analyze_and_store(
        self,
        *,
        execution_id: str,
        transcript: str,
        campaign_id: str | None = None,
        lead_id: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Analyze a call transcript with an LLM, persist the extracted analytics to CallAnalytics, and update related CRM and campaign records.
        
        If the transcript is empty or the LLM fails to produce parsable JSON, the method returns None. If the database upsert fails after parsing, the parsed result is returned but persistence/updates may be incomplete.
        
        Parameters:
            campaign_id (str | None): Optional campaign UUID (string); when provided, attempts to normalize and store on the analytics row.
            lead_id (str | None): Optional lead UUID (string); when provided, attempts to normalize and store on the analytics row and may update LeadCRM.call_status and VoicefinCampaignLead.lead_id.
            raw_payload (dict[str, Any] | None): Optional raw payload to store alongside the extracted analytics.
        
        Returns:
            dict[str, Any] | None: Parsed JSON output from the LLM (contains keys such as `sentiment`, `outcome`, `summary`) or `None` if analysis could not be produced.
        """

        if not transcript or not transcript.strip():
            return None

        messages = [
            {"role": "system", "content": _ANALYSIS_SYSTEM},
            {"role": "user", "content": _ANALYSIS_USER_TEMPLATE.format(transcript=transcript[:20000])},
        ]

        try:
            resp = await self.client.chat.completions.create(
                model=self.s.openai_chat_model,
                messages=messages,
                temperature=0.0,
            )
            content = (resp.choices[0].message.content or "").strip()
        except Exception:
            logger.exception("call_analysis_llm_failed")
            return None

        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(content)
        except Exception:
            # best-effort: find first {...} block
            try:
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1 and end > start:
                    parsed = json.loads(content[start : end + 1])
            except Exception:
                parsed = None

        if not parsed:
            return None

        sentiment = str(parsed.get("sentiment") or "") or None
        outcome = str(parsed.get("outcome") or "") or None
        summary = str(parsed.get("summary") or "") or None

        # Upsert analytics row
        try:
            res = await self.db.execute(select(CallAnalytics).where(CallAnalytics.execution_id == execution_id))
            row = res.scalar_one_or_none()
            if row is None:
                row = CallAnalytics(execution_id=execution_id)
                self.db.add(row)

            row.transcript = transcript
            row.extracted_data = parsed
            if raw_payload is not None:
                row.raw_payload = raw_payload
            if campaign_id is not None:
                try:
                    row.campaign_id = uuid.UUID(str(campaign_id))
                except Exception:
                    pass
            if lead_id is not None:
                try:
                    row.lead_id = uuid.UUID(str(lead_id))
                except Exception:
                    pass
            row.sentiment = sentiment
            row.outcome = outcome
            row.summary = summary

            # Map outcome -> CRM status
            if lead_id and outcome:
                try:
                    lid = uuid.UUID(str(lead_id))
                except Exception:
                    lid = None
                res2 = await self.db.execute(select(LeadCRM).where(LeadCRM.lead_id == lid))
                lead = res2.scalar_one_or_none()
                if lead:
                    mapped = None
                    o = outcome.upper()
                    if o in {"QUALIFIED", "REJECTED", "CALLBACK_NEEDED"}:
                        mapped = CallStatus(o)
                    if mapped:
                        lead.call_status = mapped

            # Update campaign lead row if present
            if execution_id and lead_id:
                res3 = await self.db.execute(
                    select(VoicefinCampaignLead).where(VoicefinCampaignLead.execution_id == execution_id)
                )
                cl = res3.scalar_one_or_none()
                if cl:
                    try:
                        cl.lead_id = uuid.UUID(str(lead_id))
                    except Exception:
                        pass
        except Exception:
            logger.exception("call_analysis_db_upsert_failed")
            return parsed

        return parsed
