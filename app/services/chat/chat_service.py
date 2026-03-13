import os
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger
from app.clients.openai_client import get_openai_client
from app.services.chat.memory_service import ConversationMemory
from app.services.chat.voice_state_store import VoiceStateStore
from app.services.kb.kb_service import KnowledgeBase
from app.repositories.lead_repository import LeadRepository
from app.services.rules.lead_rules import LeadRuleService
from app.repositories.state_repository import get_or_create_state, update_state
from app.repositories.session_repository import get_or_create_session
from app.repositories.chat_repository import save_message
from app.models.enums import ChatRole, SessionChannel
from app.clients.lead_ops_client import LeadOpsClient

logger = get_logger(__name__)


class ChatService:
    def __init__(self, db, user):
        """
        Initialize the ChatService and its dependent components.
        
        Parameters:
            db: Database handle used for persistent session, state, and repository operations.
            user: Optional user object representing the current authenticated user; used for token extraction and user-scoped operations.
        
        Attributes initialized:
            settings: Application settings.
            client: OpenAI client for LLM calls.
            memory: In-memory conversation memory.
            voice_state: Short-lived voice session state store.
            lead_ops_client: Client for LeadOps service.
            lead_repository: Repository for lead persistence using `db`.
            kb: Knowledge base instance.
            lead_rules: LeadRuleService coordinating rule evaluation with LeadOps and lead repository.
        """
        self.db = db
        self.user = user
        self.settings = get_settings()
        self.client = get_openai_client()
        self.memory = ConversationMemory()
        # VoiceBot should not create DB sessions. It uses short-lived state in Redis/local memory.
        self.voice_state = VoiceStateStore()
        self.lead_ops_client = LeadOpsClient()
        self.lead_repository = LeadRepository(self.db)
        self.kb = KnowledgeBase()


        self.lead_rules = LeadRuleService(
            lead_ops_client=self.lead_ops_client,
            lead_repository=self.lead_repository,
        )

    async def _handle_message(
        self,
        *,
        session_id: UUID,
        user_id: Optional[UUID],
        channel: SessionChannel,
        message: str,
        persist_db: bool = True,
    ) -> tuple[str, str]:
        """
        Handle an incoming message for a session, applying fast-path business rules or an LLM fallback and persisting session/state as appropriate.
        
        When persist_db is True, validates or creates a DB-backed session (enforcing ownership for non-voice channels), loads or creates conversation state, persists the user message, runs lead rule evaluation (fast path) and, if no rule reply, calls the LLM (slow path) and persists the bot reply, then updates conversation state. When persist_db is False (voice mode), reads and updates ephemeral voice state, runs rules or the LLM, and persists the voice state. In all modes, appends the user and assistant turns to the in-memory conversation memory.
        
        Parameters:
            session_id (UUID): Identifier for the conversation session.
            user_id (Optional[UUID]): Authenticated user ID when available; None for anonymous/voice callers.
            channel (SessionChannel): Channel the message originated from (e.g., web or voice).
            message (str): The incoming user message text.
            persist_db (bool): If True use DB-backed session/state and persist messages; if False use ephemeral voice state.
        
        Returns:
            tuple[str, str]: A pair of (reply, current_step) where `reply` is the assistant's response text and `current_step` is the step taken (`"rule_reply"` or `"llm_reply"`).
        
        Raises:
            PermissionError: If the session is owned by a different user for authenticated (non-voice) channels.
        """
        sid = str(session_id)

        # ------------------------------
        # Chatbot mode (DB sessions/state)
        # ------------------------------
        if persist_db:
            async with self.db.begin():
                # 1. Session validation + creation
                session = await get_or_create_session(
                    db=self.db,
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                )

                # Enforce session ownership ONLY for authenticated channels
                if channel != SessionChannel.voice:
                    if session.user_id and session.user_id != user_id:
                        raise PermissionError("Session does not belong to user")

                # 2. Load conversation state
                state = await get_or_create_state(self.db, session_id)

                # 3. Persist USER message
                await save_message(self.db, session_id, ChatRole.user, message)

                # 4. Business rule evaluation (fast path)
                rule_reply = await self.lead_rules.handle(self.user, message, state.context)
                if rule_reply:
                    current_step = "rule_reply"
                    reply = rule_reply
                    await save_message(self.db, session_id, ChatRole.bot, reply)
                else:
                    # 5. LLM fallback (slow path)
                    user_token = self._extract_user_token()
                    reply = await self._generate_reply(
                        session_id=session_id,
                        message=message,
                        user_id=user_id,
                        user_token=user_token,
                    )
                    current_step = "llm_reply"
                    await save_message(self.db, session_id, ChatRole.bot, reply)

                # 6. Update conversation state
                await update_state(
                    self.db,
                    session_id=session_id,
                    step=current_step,
                    context=state.context,
                )

        # ------------------------------
        # VoiceBot mode (NO DB sessions)
        # ------------------------------
        else:
            # Keep DB operations (if any) consistent within a transaction.
            async with self.db.begin():
                voice_state = await self.voice_state.get(sid)
                context = voice_state.context or {}

                # Business rules may update the context dict in-place.
                rule_reply = await self.lead_rules.handle(self.user, message, context)
                if rule_reply:
                    current_step = "rule_reply"
                    reply = rule_reply
                else:
                    reply = await self._generate_reply(
                        session_id=session_id,
                        message=message,
                        user_id=None,
                        user_token=None,
                    )
                    current_step = "llm_reply"

                await self.voice_state.set(sid, current_step=current_step, context=context)

        # Update memory (outside transaction for resilience)
        await self.memory.append(sid, "user", message)
        await self.memory.append(sid, "assistant", reply)

        return reply, current_step

    
    async def handle_web_message(self, session_id: UUID, message: str) -> tuple[str, str]:
        """
        Handle an incoming web-channel user message using a persistent DB-backed session.
        
        Delegates to the internal message handler with channel set to web and persist_db=True; the user identity is taken from self.user when available.
        
        Parameters:
            session_id (UUID): Identifier of the chat session.
            message (str): The user's message text.
        
        Returns:
            tuple[str, str]: A tuple (reply, current_step) where `reply` is the assistant's response text and `current_step` indicates the processing step (e.g., "rule_reply" or "llm_reply").
        """
        return await self._handle_message(
            session_id=session_id,
            user_id=self.user.user_id if self.user else None,
            channel=SessionChannel.web,
            message=message,
            persist_db=True,
        )
    
    async def handle_voice_message(self, session_id: str, message: str) -> tuple[str, str]:
        """
        Handle an incoming voice-channel message and return the assistant reply and processing step.
        
        Parameters:
            session_id (str): Identifier for the voice call; non-UUID IDs are accepted and normalized for internal use.
            message (str): The user's utterance.
        
        Returns:
            tuple[str, str]: A tuple (reply, current_step) where `reply` is the assistant's response text and `current_step` is a string describing how the message was handled (for example, "rule_reply" or "llm_reply").
        """
        try:
            call_uuid = UUID(str(session_id))
        except Exception:
            # Retell/Vapi sometimes send non-UUID call ids. We keep a stable UUID
            # so downstream code stays consistent.
            import uuid as _uuid

            call_uuid = _uuid.uuid5(_uuid.NAMESPACE_URL, str(session_id))

        return await self._handle_message(
            session_id=call_uuid,
            user_id=None,
            channel=SessionChannel.voice,
            message=message,
            persist_db=False,
        )

    # =========================
    # INTERNAL CHAT ENGINE ONLY
    # =========================

    # Step completion mapping (aligned with LeadOps dashboard); keys are snapshot paths
    _STEP_A_FIELDS: List[Tuple[str, str]] = [("basic_info", "dob", "Date of birth")]
    _STEP_B_FIELDS: List[Tuple[str, str]] = [("employment_ref", "employment_id", "Employment details")]
    _STEP_C_FIELDS: List[Tuple[str, str]] = [("loan_info", "loan_amount", "Loan amount")]

    def _derive_provided_missing_from_snapshot(self, data_snapshot: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Produce lists of human-readable labels for lead fields that are present and absent in a lead data snapshot.
        
        Checks each configured step field (STEP_A/B/C) against the corresponding section in `data_snapshot` and classifies its label as provided if the value is neither None nor an empty string, otherwise as missing.
        
        Returns:
            dict: A mapping with keys `"provided"` and `"missing"`. Each value is a list of labels (`str`) that are present in the snapshot and absent (or empty) respectively.
        """
        provided: List[str] = []
        missing: List[str] = []
        for step_name, key, label in (
            self._STEP_A_FIELDS + self._STEP_B_FIELDS + self._STEP_C_FIELDS
        ):
            section = (data_snapshot or {}).get(step_name) or {}
            if section and section.get(key) not in (None, ""):
                provided.append(label)
            else:
                missing.append(label)
        return {"provided": provided, "missing": missing}

    def _unwrap_lead_ops_data(self, payload: Any) -> Dict[str, Any]:
        """
        Return the inner `data` dictionary when `payload` is a LeadOps-style success response.
        
        If `payload` is a dict with `"success": True` and a `"data"` key, returns that `data` dict (or `{}` if it's falsy). If `payload` is any other dict, returns `payload` unchanged. Otherwise returns an empty dict.
        
        Returns:
            dict: The unwrapped data dict, the original dict payload, or an empty dict.
        """
        if isinstance(payload, dict) and payload.get("success") and "data" in payload:
            return payload.get("data") or {}
        return payload if isinstance(payload, dict) else {}

    async def _build_user_context(self, user_id: UUID, user_token: str) -> Dict[str, Any]:
        """
        Builds a personalized user context for LLMs, including application metadata and optionally lead details and BRE recommendations.
        
        Attempts to fetch the user's applications and sets an active application, current stage, and next steps. If settings.enrich_user_context is True and an active application has a lead_id, the function will make best-effort calls to fetch lead detail and BRE recommendations; failures during enrichment are logged and do not raise. Returned context contains keys that callers can read directly to augment prompts or decision logic.
        
        Parameters:
            user_id (UUID): Identifier of the user whose context is being built.
            user_token (str): Bearer token used to authenticate LeadOps requests.
        
        Returns:
            Dict[str, Any]: A context dictionary with the following keys:
                - has_applications (bool): True if one or more applications were found.
                - applications (list): Raw applications list from LeadOps (empty if none).
                - active_application (dict | None): Selected active application or None.
                - current_stage (str | None): Status code of the active application.
                - next_steps (list): Next action(s) for the active application.
                - missing_documents (list): Placeholder for missing documents (may be empty).
                - employment_type (str | None): Employment type if available.
                - lead_detail (dict | None): Lead detail fetched from LeadOps when available.
                - lead_provided_missing (dict | None): Mapping of provided vs missing human-readable fields derived from the lead snapshot.
                - bre_recommendations (dict | None): BRE recommendation payload when available.
        """
        context: Dict[str, Any] = {
            "has_applications": False,
            "applications": [],
            "active_application": None,
            "current_stage": None,
            "next_steps": [],
            "missing_documents": [],
            "employment_type": None,
            "lead_detail": None,
            "lead_provided_missing": None,
            "bre_recommendations": None,
        }

        if not user_id or not user_token:
            return context

        enrich = getattr(self.settings, "enrich_user_context", True)

        try:
            apps_response = await self.lead_ops_client.get_user_applications(user_token)
            if not (apps_response and apps_response.get("success") and apps_response.get("data")):
                return context

            apps_data = apps_response["data"]
            applications = apps_data.get("applications", [])
            if not applications:
                return context

            context["has_applications"] = True
            context["applications"] = applications

            # Current lead: first in-progress, else most recent (same rule as rules engine)
            active_statuses = [
                "PERSONAL_DETAILS_CAPTURED",
                "EMPLOYMENT_DETAILS_CAPTURED",
                "LOAN_DETAILS_CAPTURED",
                "LENDER_SELECTED",
                "PRE_ELIGIBILITY_CHECK",
                "APPLICATION_IN_PROGRESS",
            ]
            active_apps = [a for a in applications if a.get("status_code") in active_statuses]
            current_app = active_apps[0] if active_apps else applications[0]
            context["active_application"] = current_app
            context["current_stage"] = current_app.get("status_code")
            context["next_steps"] = [current_app.get("next_action")] if current_app.get("next_action") else []

            if not enrich:
                return context

            lead_id = current_app.get("lead_id")
            if not lead_id:
                logger.info("context_enrich_skipped", reason="no_lead_id")
                return context

            lead_id_str = str(lead_id)

            # Fetch lead detail (get_lead) – best-effort; fallback to dashboard-only on failure
            try:
                lead_resp = await self.lead_ops_client.get_lead(lead_id=lead_id_str, user_token=user_token)
                lead = self._unwrap_lead_ops_data(lead_resp) if lead_resp else {}
                if lead:
                    context["lead_detail"] = lead
                    data_snapshot = lead.get("data_snapshot") or {}
                    context["lead_provided_missing"] = self._derive_provided_missing_from_snapshot(data_snapshot)
            except Exception as e:
                logger.warning("context_lead_fetch_failed", lead_id=lead_id_str, error=str(e))

            # Fetch BRE recommendations – best-effort
            try:
                rec_resp = await self.lead_ops_client.bre_get_recommendations(lead_id=lead_id_str, user_token=user_token)
                rec_data = self._unwrap_lead_ops_data(rec_resp) if rec_resp else {}
                if rec_data and rec_data.get("selected_lenders"):
                    context["bre_recommendations"] = rec_data
                else:
                    context["bre_recommendations"] = rec_data
            except Exception as e:
                logger.warning("context_bre_fetch_failed", lead_id=lead_id_str, error=str(e))

            logger.info(
                "context_built",
                has_lead_detail=context.get("lead_detail") is not None,
                has_bre=bool(context.get("bre_recommendations") and (context.get("bre_recommendations") or {}).get("selected_lenders")),
            )
        except Exception as e:
            logger.warning("user_context_fetch_failed", error=str(e), exc_info=True)

        return context
    
    def _format_user_context_for_llm(self, context: Dict[str, Any]) -> str:
        """
        Builds a human-readable USER CONTEXT block describing the active application, provided vs missing lead fields, and top lender recommendations for inclusion in an LLM prompt.
        
        Returns:
            A single formatted string containing sections for APPLICATIONS, PROVIDED vs MISSING (for the current application), and TOP LENDER RECOMMENDATIONS (if available). Returns "USER CONTEXT: No active loan applications found." when no active applications are present.
        """
        if not context.get("has_applications"):
            return "USER CONTEXT: No active loan applications found."

        parts: List[str] = ["USER CONTEXT (about the logged-in borrower):"]

        # ---- APPLICATIONS ----
        parts.append("\n--- APPLICATIONS ---")
        if context.get("active_application"):
            app = context["active_application"]
            parts.append(f"- Active application: {app.get('loan_type_display', app.get('loan_type_code', 'Unknown'))}")
            parts.append(f"- Status: {app.get('status_display', app.get('status_code', 'Unknown'))}")
            parts.append(f"- Progress: {app.get('progress', {}).get('percentage', 0)}% complete")
            progress = app.get("progress", {})
            completed = []
            if progress.get("basic_info_provided"):
                completed.append("Basic Information (Step A)")
            if progress.get("employment_detail_provided"):
                completed.append("Employment Details (Step B)")
            if progress.get("loan_info_provided"):
                completed.append("Loan Information (Step C)")
            if completed:
                parts.append(f"- Completed steps: {', '.join(completed)}")
            if app.get("next_action"):
                parts.append(f"- Next action: {app.get('next_action')}")
        total = len(context.get("applications") or [])
        parts.append(f"- Total applications: {total}")

        # ---- PROVIDED vs MISSING (from lead detail) ----
        pm = context.get("lead_provided_missing")
        if pm and isinstance(pm, dict):
            parts.append("\n--- FOR THIS APPLICATION: PROVIDED vs MISSING ---")
            prov = pm.get("provided") or []
            miss = pm.get("missing") or []
            if prov:
                parts.append(f"- Provided: {', '.join(prov)}")
            if miss:
                parts.append(f"- Missing: {', '.join(miss)}")
            if not prov and not miss:
                parts.append("- (Unable to determine from current data)")

        # ---- TOP LENDER RECOMMENDATIONS (from BRE) ----
        bre = context.get("bre_recommendations") or {}
        lenders = bre.get("selected_lenders") if isinstance(bre, dict) else None
        if lenders and isinstance(lenders, list) and len(lenders) > 0:
            parts.append("\n--- TOP LENDER RECOMMENDATIONS (from BRE) ---")
            for i, row in enumerate(lenders[:10], start=1):
                if not isinstance(row, dict):
                    continue
                name = row.get("name") or f"Lender {i}"
                line_parts = [f"{i}. {name}"]
                if row.get("principalAmount"):
                    line_parts.append(f"Amount: {row.get('principalAmount')}")
                if row.get("interestRate"):
                    line_parts.append(f"Rate: {row.get('interestRate')}")
                if row.get("loanTenure"):
                    line_parts.append(f"Tenure: {row.get('loanTenure')} months")
                if row.get("emi"):
                    line_parts.append(f"EMI: {row.get('emi')}")
                if row.get("approvedChance"):
                    line_parts.append(f"Approval chance: {row.get('approvedChance')}")
                if row.get("decision"):
                    line_parts.append(f"Decision: {row.get('decision')}")
                parts.append(" — ".join(line_parts))

        return "\n".join(parts)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _generate_reply(self, session_id: UUID, message: str, user_id: UUID = None, user_token: str = None) -> str:
        """
        Generate an assistant reply for the given session by combining recent conversation history, an optional enriched user context, and optional knowledge-base context, then querying the configured LLM.
        
        When a valid user_id and user_token are provided, user-specific context (applications, lead snapshot, BRE recommendations) is fetched and formatted into the system prompt. If the knowledge base is enabled and returns high-scoring hits, those documents are included as additional system context. The function appends recent conversation history and the new user message, sends the composed messages to the chat model, and returns the model's response text.
        
        Parameters:
            user_id (UUID | None): Optional user identifier used to fetch and enrich the USER CONTEXT; omitted or None disables user-context enrichment.
            user_token (str | None): Optional bearer token required to fetch the user's lead/application details when enriching context.
        
        Returns:
            reply (str): The assistant's reply text produced by the LLM (empty string if the model returned no content).
        """
        start = time.perf_counter()
        history = await self.memory.get_history(session_id=str(session_id), limit=20)

        # roinet_system = (
        #     "You are Roinet Fintech’s support assistant.\n\n"
        #     "Scope:\n"
        #     "- Answer ONLY questions related to the Roinet Fintech platform: its products, services, features, workflows, "
        #     "business logic, and user-facing functionality.\n"
        #     "- This includes loans/lending/credit (EMI, repayment, interest, eligibility, disbursement, rejection), "
        #     "onboarding/KYC, accounts, transactions, wallets, payments, settlements, refunds, user roles/permissions, "
        #     "dashboards, and support flows.\n\n"
        #     "Grounding:\n"
        #     "- Use ONLY the provided Roinet documentation context.\n"
        #     "- Do NOT invent features, policies, eligibility rules, timelines, fees, or behaviors.\n\n"
        #     "Out of scope:\n"
        #     "- If unrelated to Roinet/fintech, politely say you can only help with Roinet-related questions.\n"
        #     "- If the user asks generic finance definitions (e.g., 'What is a loan?', 'What is EMI?', 'Explain interest rate'), "
        #     "do NOT explain. Redirect to how it works in Roinet.\n\n"
        #     "Response rules:\n"
        #     "- Never stay silent: always provide a helpful response.\n"
        #     "- Be concise, factual, professional. Use bullets for steps/documents.\n"
        #     "- Ask at most 2 clarifying questions if needed.\n"
        #     "- Do NOT mention internal files, document names, PDFs, indexes, or knowledge-base mechanics.\n"
        # )

        # Build user context if available (dashboard + optional lead detail + BRE when ENRICH_USER_CONTEXT=True)
        user_context_str = ""
        if user_id and user_token:
            try:
                user_context = await self._build_user_context(user_id, user_token)
                user_context_str = self._format_user_context_for_llm(user_context)
            except Exception as e:
                logger.warning("user_context_build_failed", error=str(e), exc_info=True)
                
        roinet_system = (
            "You are Roinet Fintech’s support assistant.\n\n"
            "Scope:\n"
            "- Answer questions related to Roinet Fintech and the finance domain (loans/lending/credit, EMI, repayment, "
            "interest, eligibility, disbursement, rejection), onboarding/KYC, accounts, transactions, wallets, payments, "
            "settlements, refunds, and support flows.\n\n"
            "Grounding:\n"
            "- Use ONLY the provided documentation context and, when present, the USER CONTEXT blocks below.\n"
            "- The USER CONTEXT describes the logged-in borrower: their applications, what they have provided vs what is missing, "
            "and (when available) top lender recommendations with EMI, rate, approval chance, etc. Prefer this data when the user "
            "asks about \"my application\", \"my lenders\", \"what's missing\", \"EMI for lender X\", \"which lender to choose\", "
            "or \"why is my approval chance low/high\".\n"
            "- If the documentation or USER CONTEXT does not contain the answer, say you don't have enough information and ask 1–2 clarifying questions.\n"
            "- Do NOT invent features, policies, eligibility rules, timelines, fees, or behaviors.\n\n"
            "Response rules:\n"
            "- Be concise, factual, professional. Use bullets for steps.\n"
            "- Do NOT mention internal files, document names, PDFs, indexes, or knowledge-base mechanics.\n"
        )
        
        if user_context_str:
            roinet_system += f"\n{user_context_str}\n\n"

        messages = [{"role": "system", "content": roinet_system}]

        # Knowledge base search (soft gate - don't reject if no hits)
        if self.settings.kb_enabled:
            hits = await self.kb.search(message, top_k=self.settings.kb_top_k)
            hits = [(c, s) for (c, s) in hits if s >= self.settings.kb_min_score]

            if hits:
                # Add KB context when available
                context_blocks = []
                for c, score in hits:
                    fname = os.path.basename(c.source)
                    context_blocks.append(f"[Source: {fname} | score={score:.2f}]\n{c.text}")

                context = "\n\n---\n\n".join(context_blocks)
                messages.append({"role": "system", "content": f"ROINET_DOCS_CONTEXT\n{context}"})
            else:
                # No KB hits, but still allow LLM to answer using general knowledge + user context
                logger.info(f"No KB hits for message, using LLM with user context only. Session: {session_id}")
                # Don't reject - let LLM use general knowledge and user context

        # Fix: Map bot→assistant for OpenAI compatibility
        role_map = {"bot": "assistant"}
        messages += [{"role": role_map.get(m.role, m.role), "content": m.content} for m in history]
        messages.append({"role": "user", "content": message})

        resp = await self.client.chat.completions.create(
            model=self.settings.openai_chat_model,
            messages=messages,
            temperature=0.2,
            max_tokens=500,
        )

        reply = resp.choices[0].message.content or ""

        logger.info(
            "chat_complete",
            session_id=session_id,
            input_chars=len(message),
            output_chars=len(reply),
            duration_ms=(time.perf_counter() - start) * 1000,
        )
        return reply

    def _extract_user_token(self) -> str | None:
        """
        Return the bearer token from the current user object if available.
        
        Returns:
            str | None: The user's bearer token when present and accessible, otherwise None.
        """
        try:
            if self.user and getattr(self.user, "token", None):
                return self.user.token
        except Exception:
            pass
        return None