from __future__ import annotations

from typing import Any, Optional, List, Dict

from app.clients.config_client import _current_token  # only token contextvar


class LeadRuleService:
    def __init__(self, lead_ops_client, lead_repository):
        """
        Initialize the service with its dependencies and default lead-status configuration.
        
        Stores the provided lead operations client and lead repository on the instance. Defines
        active_status_priority as an ordered list of status codes to prefer when selecting a lead
        (the earlier a status appears, the higher its selection priority) and defines closed_status
        as the set of terminal status codes treated as closed. Edit active_status_priority to match
        your system's actual status codes if needed.
        """
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
        """
        Extract the nested `data` dictionary from a response-like payload or return a safe dict.
        
        Parameters:
            payload (Any): Response payload that may be a dict containing a `"data"` dict.
        
        Returns:
            dict: The inner `data` dict if present, otherwise the original payload if it's a dict, or an empty dict.
        """
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _has_any(text: str, phrases: List[str]) -> bool:
        """
        Check whether any of the given phrases appear in the text (case-insensitive).
        
        Parameters:
            text (str): The text to search; None or empty string is treated as empty.
            phrases (List[str]): Substrings to look for in `text`.
        
        Returns:
            bool: `True` if any phrase is found as a substring of `text`, `False` otherwise.
        """
        t = (text or "").lower()
        return any(p in t for p in phrases)

    @staticmethod
    def _infer_loan_type_code(text: str) -> Optional[str]:
        """
        Infer a loan type code from free-form text.
        
        Parameters:
            text (str): Text to scan for loan-type keywords (e.g., user message or application notes).
        
        Returns:
            loan_type_code (Optional[str]): A loan type code corresponding to detected keywords (for example "PERSONAL_LOAN", "BUSINESS_LOAN", etc.), or `None` if no loan type is detected. Replace these example codes with your system's canonical loan_type_code values as needed.
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
        Infer a canonical lead status code from free-form text by matching known keywords to status codes.
        
        Matches keywords to these status codes: "approved" -> "APPROVED", "rejected"/"declined" -> "REJECTED", "pending" -> "PENDING", "in progress"/"processing" -> "IN_PROGRESS", "under review" -> "UNDER_REVIEW", "disbursed" -> "DISBURSED". Returns None if no keyword is found.
        
        Parameters:
            text (str): Free-form text to inspect for status-related keywords.
        
        Returns:
            Optional[str]: The matched status code, or `None` if no match was found.
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
        Select the most relevant lead from a list, preferring active statuses configured on the service and falling back to the most recent.
        
        Parameters:
            leads (List[Dict[str, Any]]): List of lead objects (expected ordered by `created_at` descending as returned by Lead Ops).
        
        Returns:
            dict: The chosen lead object when available.
            None: If the input list is empty.
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
        Resolve the most appropriate lead_id for the user by using filters inferred from the message and a cached context.
        
        Infers loan type and status from msg_text, reuses a cached lead_id when the cached loan type matches the inferred one (or when no loan type was requested), and queries the lead service with inferred filters. If no lead is found, retries without filters. On success, caches `lead_id` and `loan_type_code` in state_context.
        
        Parameters:
            token (str): User authentication token passed to the lead operations client.
            state_context (dict): Mutable context used as a cache; may be updated with keys `lead_id` and `loan_type_code`.
            msg_text (str): User message used to infer loan type and status filters.
        
        Returns:
            Optional[str]: The resolved `lead_id` as a string if found, `None` otherwise.
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
        """
        Handle a user message to provide loan application status or loan recommendations when the intent is explicit.
        
        Processes the incoming text to detect explicit status-tracking or recommendation intents. For status intent, fetches the current lead and returns a short formatted status summary. For recommendation intent, fetches or evaluates recommendations and returns a formatted list with the top options. Returns None for advisory/education queries, when the user or token is missing, or when no lead-related action should be taken.
        
        Parameters:
            user: The authenticated user object; if falsy, the handler returns None.
            message (str): The user's message text to analyze for intent.
            state_context (dict): Mutable per-user context used for caching current lead and loan type.
        
        Returns:
            str: A user-facing message with status or recommendation details when applicable.
            None: When deferring to other handlers (advisory queries, missing token/user, or no explicit lead intent).
        """
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