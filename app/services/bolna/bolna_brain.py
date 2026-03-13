from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openai_client import get_openai_client
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.crm_models import LeadCRM, ServiceablePincode
from app.models.voicefin_models import VoicefinLeadContact
from app.services.kb.kb_service import KnowledgeBase


logger = get_logger(__name__)
_PINCODE_RE = re.compile(r"\b(\d{6})\b")


@dataclass
class BolnaBrain:
    """Generate the agent's next response for Bolna using your Custom LLM + RAG + DB context.

    Bolna calls this backend's OpenAI-compatible endpoint (`/v1/chat/completions`) and
    passes the conversation `messages`. This brain augments those messages with:
    - Lead context (name, pincode, current CRM status)
    - Pincode serviceability (if available)
    - Roinet knowledge base snippets (local RAG)
    """

    db: AsyncSession
    kb: KnowledgeBase | None = None

    def __post_init__(self) -> None:
        self.s = get_settings()
        self.client = get_openai_client()
        if self.kb is None and self.s.kb_enabled:
            self.kb = KnowledgeBase()

    async def generate_reply(self, *, messages: list[dict[str, Any]], user_data: dict[str, Any] | None = None) -> str:
        user_data = user_data or {}

        # Extract last user message
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = str(m.get("content") or "")
                break

        lead_ctx = await self._lead_context(user_data=user_data, last_user=last_user)
        kb_ctx = await self._kb_context(last_user)

        # Keep original system prompt(s) from Bolna, then inject our own context.
        system_msgs = [m for m in messages if m.get("role") == "system"]
        conv_msgs = [m for m in messages if m.get("role") != "system"]

        injected = {
            "role": "system",
            "content": (
                "INTERNAL CONTEXT (use to answer the user naturally; do not mention this block):\n"
                f"{lead_ctx}\n\n{kb_ctx}".strip()
            ),
        }

        final_messages = system_msgs + [injected] + conv_msgs

        resp = await self.client.chat.completions.create(
            model=self.s.openai_chat_model,
            messages=final_messages,
            temperature=0.4,
        )

        try:
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            logger.exception("llm_response_parse_failed")
            return "Sorry, mujhe abhi thodi si problem ho rahi hai. Kya aap ek baar phir se bol sakte hain?"

    async def _lead_context(self, *, user_data: dict[str, Any], last_user: str) -> str:
        parts: list[str] = []

        lead_id = user_data.get("lead_id") or user_data.get("leadId")
        lead_uuid: uuid.UUID | None = None
        if lead_id:
            try:
                lead_uuid = uuid.UUID(str(lead_id))
            except Exception:
                lead_uuid = None

        if lead_uuid:
            # VoicefinLeadContact (name/pincode)
            try:
                res = await self.db.execute(
                    select(VoicefinLeadContact).where(VoicefinLeadContact.lead_id == lead_uuid)
                )
                contact = res.scalar_one_or_none()
                if contact:
                    if contact.name:
                        parts.append(f"Lead name: {contact.name}")
                    if contact.pincode:
                        parts.append(f"Lead pincode: {contact.pincode}")
            except Exception:
                pass

            # CRM lead (phone + status)
            try:
                res = await self.db.execute(select(LeadCRM).where(LeadCRM.lead_id == lead_uuid))
                lead = res.scalar_one_or_none()
                if lead:
                    parts.append(f"Lead phone: {lead.phone_number}")
                    if lead.call_status:
                        parts.append(f"Current lead status: {lead.call_status}")
            except Exception:
                pass

        # If user just shared a pincode, also include serviceability
        pincode = None
        m = _PINCODE_RE.search(last_user)
        if m:
            pincode = m.group(1)
        if not pincode:
            pincode = user_data.get("pincode")
        if pincode:
            try:
                res = await self.db.execute(select(ServiceablePincode).where(ServiceablePincode.pincode == str(pincode)))
                pin = res.scalar_one_or_none()
                if pin:
                    parts.append(f"Pincode serviceability: {pin.status}")
            except Exception:
                pass

        if not parts:
            return "(No lead context)"
        return "\n".join(parts)

    async def _kb_context(self, query: str) -> str:
        if not self.kb or not query.strip():
            return "(No KB context)"
        try:
            hits = await self.kb.search(query)
        except Exception:
            logger.exception("kb_search_failed")
            return "(No KB context)"

        useful: list[str] = []
        for chunk, score in hits:
            if score < float(self.s.kb_min_score):
                continue
            txt = (chunk.text or "").strip()
            if not txt:
                continue
            useful.append(f"[score={score:.2f}] {txt}")

        if not useful:
            return "(No KB context)"
        return "KNOWLEDGE BASE SNIPPETS:\n" + "\n\n".join(useful[: self.s.kb_top_k])