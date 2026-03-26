from __future__ import annotations

from typing import Any, Optional, List, Dict

from app.clients.config_client import _current_token  # only token contextvar


class LeadRuleService:
    def __init__(self, lead_ops_client, lead_repository):
        self.lead_ops_client = lead_ops_client
        self.lead_repository = lead_repository

        # Prefer active leads first (edit these to match YOUR actual status codes)
        self.active_status_priority = [
            "IN_PROGRESS",
            "UNDER_REVIEW",
            "PENDING",
            "LEAD_CREATED",
            "DOC_PENDING",
            "KYC_PENDING",
        ]
        self.closed_status = {"APPROVED", "REJECTED", "CLOSED", "DISBURSED"}

    @staticmethod
    def _unwrap_success(payload: Any) -> dict:
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _has_any(text: str, phrases: List[str]) -> bool:
        t = (text or "").lower()
        return any(p in t for p in phrases)

    @staticmethod
    def _infer_loan_type_code(text: str) -> Optional[str]:
        """
        IMPORTANT: Replace returned codes with your system's real loan_type_code values.
        """
        t = (text or "").lower()

        mapping = [
            (["personal loan", "personal"], "PERSONAL_LOAN"),
            (["business loan", "business", "msme"], "BUSINESS_LOAN"),
            (["home loan", "housing"], "HOME_LOAN"),
            (["education loan", "student"], "EDUCATION_LOAN"),
            (["gold loan"], "GOLD_LOAN"),
            (["vehicle loan", "car loan", "bike loan", "two wheeler"], "VEHICLE_LOAN"),
        ]
        for keywords, code in mapping:
            if any(k in t for k in keywords):
                return code
        return None

    @staticmethod
    def _infer_status_code(text: str) -> Optional[str]:
        """
        Optional: Only works if your /leads supports these status_code values.
        Replace with your actual status codesoinet lead statuses if different.
        """
        t = (text or "").lower()

        if "approved" in t:
            return "APPROVED"
        if "rejected" in t or "declined" in t:
            return "REJECTED"
        if "pending" in t:
            return "PENDING"
        if "in progress" in t or "processing" in t:
            return "IN_PROGRESS"
        if "under review" in t:
            return "UNDER_REVIEW"
        if "disbursed" in t:
            return "DISBURSED"
        return None

    def _pick_best_lead(self, leads: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Leads list is already ordered by created_at desc in Lead Ops.
        We still prefer "active" statuses if present.
        """
        if not leads:
            return None

        # If any lead has active status, pick the first one by priority
        status_buckets: Dict[str, List[Dict[str, Any]]] = {}
        for lead in leads:
            sc = str(lead.get("status_code") or lead.get("status") or "")
            status_buckets.setdefault(sc, []).append(lead)

        for sc in self.active_status_priority:
            if sc in status_buckets and status_buckets[sc]:
                return status_buckets[sc][0]

        # Otherwise fallback to latest lead
        return leads[0]

    async def _get_current_lead_id(self, token: str, state_context: dict, msg_text: str) -> Optional[str]:
        """
        Automatically determine lead_id:
          - If user message says loan type, filter by loan_type_code
          - If user message says approved/rejected/pending, filter by status_code
          - Cache lead_id in state_context
        """
        # If cached and user did NOT ask a different loan type explicitly, reuse
        requested_loan_type = self._infer_loan_type_code(msg_text)
        requested_status = self._infer_status_code(msg_text)

        cached = state_context.get("lead_id")
        cached_loan_type = state_context.get("loan_type_code")

        if cached and (not requested_loan_type or requested_loan_type == cached_loan_type):
            return cached

        leads = await self.lead_ops_client.list_leads(
            user_token=token,
            loan_type_code=requested_loan_type,
            status_code=requested_status,
        )
        best = self._pick_best_lead(leads)
        if not best:
            # fallback: fetch without filters
            leads = await self.lead_ops_client.list_leads(user_token=token)
            best = self._pick_best_lead(leads)

        if not best:
            return None

        lead_id = str(best.get("lead_id") or "")
        if lead_id:
            state_context["lead_id"] = lead_id
            state_context["loan_type_code"] = best.get("loan_type_code") or requested_loan_type
        return lead_id or None

    async def handle(self, user, message: str, state_context: dict) -> str | None:
        if not user:
            return None

        token = _current_token.get()
        if not token:
            return None

        text = (message or "").strip()
        lower = text.lower()

        # -------------------------
        # Intent guards (VERY IMPORTANT)
        # -------------------------
        # If user is asking advisory/education questions, DO NOT trigger lead-status shortcut.
        advisory_terms = [
            "credit score",
            "improve my credit",
            "improve credit",
            "increase my credit",
            "how can i improve",
            "how do i improve",
            "tips to improve",
            "improve cibil",
            "cibil",
        ]
        if any(t in lower for t in advisory_terms):
            # Let LLM/RAG answer from KB (do not hijack into lead status)
            return None

        # Status intent must be explicit
        status_triggers = [
            "loan status",
            "application status",
            "lead status",
            "status of my",
            "track",
            "tracking",
            "progress",
            "where is my application",
            "current status",
            "check status",
        ]
        is_status_intent = any(t in lower for t in status_triggers)

        # Recommendation intent must be explicit
        reco_triggers = [
            "recommend",
            "recommendation",
            "best loan",
            "suggest",
            "which loan",
            "which lender",
            "loan offer",
            "loan offers",
        ]
        is_reco_intent = any(t in lower for t in reco_triggers)

        # -------------------------
        # STATUS / TRACKING  (only when explicit)
        # -------------------------
        if is_status_intent:
            lead_id = await self._get_current_lead_id(token, state_context, lower)
            if not lead_id:
                return "I couldn’t find any loan application for your account yet."

            lead_resp = await self.lead_ops_client.get_lead(lead_id=lead_id, user_token=token)
            if not lead_resp:
                return "I couldn’t fetch your application details right now. Please try again."

            lead = self._unwrap_success(lead_resp)

            status_code = lead.get("status_code") or lead.get("status") or "UNKNOWN"
            loan_type_code = lead.get("loan_type_code") or state_context.get("loan_type_code") or ""

            lines = ["Here’s your current loan/application status:"]
            if loan_type_code:
                lines.append(f"- **Loan type:** {loan_type_code}")
            lines.append(f"- **Status:** {status_code}")
            return "\n".join(lines)

        # -------------------------
        # RECOMMENDATIONS (only when explicit)
        # -------------------------
        if is_reco_intent:
            lead_id = await self._get_current_lead_id(token, state_context, lower)
            if not lead_id:
                return "To recommend loans, I need an active application. Please start an application first."

            rec_resp = await self.lead_ops_client.bre_get_recommendations(lead_id=lead_id, user_token=token)
            rec_data = self._unwrap_success(rec_resp or {})
            selected = rec_data.get("selected_lenders") or []

            if not selected:
                await self.lead_ops_client.bre_evaluate_lead(lead_id=lead_id, user_token=token)
                rec_resp = await self.lead_ops_client.bre_get_recommendations(lead_id=lead_id, user_token=token)
                rec_data = self._unwrap_success(rec_resp or {})
                selected = rec_data.get("selected_lenders") or []

            if not selected:
                return "I couldn’t find matching offers for your application right now."

            best = selected[0]
            best_name = best.get("name") or "Option 1"

            lines = [f"Based on your current profile, **{best_name}** looks like the best match."]
            lines.append("Top 3 options:")
            for i, item in enumerate(selected[:3], start=1):
                name = item.get("name") or f"Option {i}"
                emi = item.get("emi")
                rate = item.get("interestRate")
                amount = item.get("principalAmount")
                tenure = item.get("loanTenure")

                parts = []
                if amount:
                    parts.append(f"Amount: {amount}")
                if rate:
                    parts.append(f"Rate: {rate}")
                if tenure:
                    parts.append(f"Tenure: {tenure} months")
                if emi:
                    parts.append(f"EMI: {emi}")

                lines.append(f"{i}. **{name}** — " + " | ".join(parts))

            return "\n".join(lines)

        return None