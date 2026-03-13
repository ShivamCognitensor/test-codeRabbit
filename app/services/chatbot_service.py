"""
Chatbot Service - AI-powered FAQ, lead qualification, lender selection assistance.

Features:
- OpenAI GPT integration for natural conversations
- Context enrichment with user's lead data and BRE recommendations
- FAQ knowledge base for common questions
- Lender selection guidance based on BRE results
- Support for both authenticated and public (anonymous) chat
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import ChatConversation, ChatMessage
from app.core.config import settings

logger = logging.getLogger(__name__)


# FAQ knowledge base for fallback responses
FAQ_DATA = {
    "loan_types": {
        "question": "What types of loans do you offer?",
        "answer": "We offer various loan types including Personal Loans, Business Loans, Home Loans, and Vehicle Loans. Each has different eligibility criteria and interest rates. Personal loans are most popular for immediate needs.",
        "keywords": ["loan", "types", "offer", "available", "options", "kinds"],
    },
    "eligibility": {
        "question": "What are the eligibility criteria for a loan?",
        "answer": "Eligibility depends on:\n• Age: 21-65 years\n• Income: Minimum ₹25,000/month for salaried\n• Credit Score: 650+ preferred\n• Employment: Minimum 1 year experience\n• Documents: PAN, Aadhaar, Income proof",
        "keywords": ["eligibility", "qualify", "requirements", "criteria", "need", "eligible"],
    },
    "documents": {
        "question": "What documents are required?",
        "answer": "Required documents:\n1. Identity: PAN Card, Aadhaar Card\n2. Income Proof: 3 months salary slips or ITR\n3. Bank Statements: Last 6 months\n4. Address Proof: Utility bill or rent agreement\n5. Employment: Offer letter or appointment letter",
        "keywords": ["documents", "papers", "required", "need", "submit", "upload", "kyc"],
    },
    "interest_rates": {
        "question": "What are the interest rates?",
        "answer": "Interest rates vary by lender and your profile:\n• Personal Loans: 10.5% to 24% p.a.\n• Business Loans: 14% to 28% p.a.\n• Home Loans: 8.5% to 12% p.a.\n\nYour actual rate depends on credit score, income, and lender policies. Our BRE shows you personalized rates!",
        "keywords": ["interest", "rate", "rates", "percentage", "cost", "roi"],
    },
    "application_process": {
        "question": "How do I apply for a loan?",
        "answer": "Apply in 5 easy steps:\n1. Register with your mobile number\n2. Fill basic details (income, employment)\n3. Upload required documents\n4. Get instant eligibility check\n5. Choose from matched lender offers\n\nThe entire process can be completed in under 10 minutes!",
        "keywords": ["apply", "application", "process", "how", "start", "begin"],
    },
    "loan_status": {
        "question": "How can I check my loan status?",
        "answer": "Check your loan status:\n1. Login to your dashboard\n2. View 'My Applications' section\n3. See current stage and timeline\n\nStages: Lead Created → Documents Verified → BRE Matched → Lender Selected → Application Submitted → Approved → Disbursed",
        "keywords": ["status", "check", "track", "where", "progress", "stage"],
    },
    "repayment": {
        "question": "What are the repayment options?",
        "answer": "Repayment options:\n• EMI: Fixed monthly installments via auto-debit\n• Prepayment: Pay extra anytime (some lenders charge 2-4% fee)\n• Foreclosure: Close loan early with remaining principal\n• Tenure: 12 to 60 months depending on loan type",
        "keywords": ["repayment", "pay", "emi", "installment", "payment", "prepay", "close"],
    },
    "bre_recommendations": {
        "question": "How do I choose from the lender recommendations?",
        "answer": "To choose the best lender:\n1. Compare interest rates - lower is better\n2. Check EMI amount - fits your budget?\n3. Look at processing fees - varies by lender\n4. Consider tenure - longer = lower EMI but more interest\n5. Check approval chances - our score indicates likelihood\n\nI can help you compare your specific options!",
        "keywords": ["recommend", "lender", "choose", "select", "compare", "which", "best", "option"],
    },
}

# System prompt for OpenAI
SYSTEM_PROMPT = """You are a helpful financial assistant for Roinet LMS, a loan management platform.

Your role:
1. Answer questions about loans, eligibility, and the application process
2. Help users understand their loan options and BRE recommendations
3. Guide users through the application process
4. Be concise, professional, and helpful

Important guidelines:
- Keep responses under 150 words unless explaining complex topics
- Use bullet points for lists
- Be encouraging but realistic about eligibility
- Never make specific promises about approval
- If you don't know something, say so and suggest contacting support
- Always recommend using the official dashboard for actions

{context}"""


class ChatbotService:
    """Service for AI-powered chatbot interactions."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._openai_client = None
        self._lead_ops_client = None
    
    @property
    def openai_client(self):
        """Lazy load OpenAI client."""
        if self._openai_client is None:
            from app.clients.openai_client import openai_client
            self._openai_client = openai_client
        return self._openai_client
    
    @property
    def lead_ops_client(self):
        """Lazy load Lead Ops client."""
        if self._lead_ops_client is None:
            from app.clients.lead_ops_client import lead_ops_client
            self._lead_ops_client = lead_ops_client
        return self._lead_ops_client
    
    async def process_message(
        self,
        session_id: str,
        user_message: str,
        user_id: Optional[UUID] = None,
        user_token: Optional[str] = None,
        context_type: Optional[str] = None,
        context_id: Optional[UUID] = None,
        is_public: bool = False,
    ) -> Tuple[ChatConversation, ChatMessage, str]:
        """
        Process a user message and generate a response.
        
        Args:
            session_id: Chat session identifier
            user_message: User's message
            user_id: Authenticated user's ID (None for public chat)
            user_token: JWT token for fetching user context
            context_type: Context type (e.g., 'lender_selection', 'lead')
            context_id: Related entity ID (e.g., lead_id)
            is_public: Whether this is a public (unauthenticated) chat
        
        Returns:
            Tuple of (conversation, user_message, assistant_response)
        """
        # Get or create conversation
        conversation = await self._get_or_create_conversation(
            session_id, user_id, context_type, context_id, is_public
        )
        
        # Check message limits for public chat
        if is_public:
            message_count = await self._get_message_count(conversation.id)
            if message_count >= settings.PUBLIC_CHAT_MAX_MESSAGES * 2:  # *2 for user+assistant
                return conversation, None, "You've reached the message limit for public chat. Please register to continue our conversation and get personalized loan recommendations!"
        
        # Save user message
        user_msg = ChatMessage(
            conversation_id=conversation.id,
            role="user",
            content=user_message[:settings.PUBLIC_CHAT_MAX_MESSAGE_LENGTH] if is_public else user_message,
        )
        
        # Get conversation history
        history = await self._get_recent_messages(conversation.id)
        
        # Build context
        user_context = None
        if not is_public and user_id and user_token and settings.ENRICH_USER_CONTEXT:
            user_context = await self.lead_ops_client.get_user_context(user_id, user_token)
        
        # Generate response
        if self.openai_client.is_enabled:
            response, intent = await self._generate_ai_response(
                user_message=user_message,
                history=history,
                user_context=user_context,
                context_type=context_type,
                is_public=is_public,
            )
        else:
            intent, response = self._generate_fallback_response(
                user_message, context_type, user_context
            )
        
        user_msg.detected_intent = intent
        self.db.add(user_msg)
        
        # Save assistant response
        assistant_msg = ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=response,
        )
        self.db.add(assistant_msg)
        
        await self.db.commit()
        await self.db.refresh(user_msg)
        await self.db.refresh(assistant_msg)
        
        return conversation, user_msg, response
    
    async def _generate_ai_response(
        self,
        user_message: str,
        history: List[Dict[str, str]],
        user_context: Optional[Dict[str, Any]],
        context_type: Optional[str],
        is_public: bool,
    ) -> Tuple[str, str]:
        """Generate response using OpenAI."""
        # Build context block
        context_block = self._build_context_block(user_context, context_type, is_public)
        
        # Build messages
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context_block)},
        ]
        
        # Add conversation history
        for msg in history[-settings.CHATBOT_MAX_HISTORY:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Add current message
        messages.append({"role": "user", "content": user_message})
        
        try:
            response = await self.openai_client.chat_completion(
                messages=messages,
                temperature=0.7,
                max_tokens=500,
            )
            
            # Detect intent from response
            intent = self._detect_intent(user_message, response)
            return response, intent
        
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            # Fallback to rule-based response
            intent, response = self._generate_fallback_response(
                user_message, context_type, user_context
            )
            return response, intent
    
    def _build_context_block(
        self,
        user_context: Optional[Dict[str, Any]],
        context_type: Optional[str],
        is_public: bool,
    ) -> str:
        """Build context information for the system prompt."""
        blocks = []
        
        if is_public:
            blocks.append("""
This is a PUBLIC chat session (unauthenticated user).
- Keep responses general and helpful
- Encourage registration for personalized recommendations
- Don't ask for or store personal information
- Guide them to register for full features""")
            return "\n".join(blocks)
        
        if user_context and user_context.get("has_leads"):
            # Active lead context
            if user_context.get("active_lead"):
                lead = user_context["active_lead"]
                requested_amount = lead.get("requested_amount") or 0

                blocks.append(f"""
USER'S CURRENT APPLICATION:
- Lead Number: {lead.get('lead_number', 'N/A')}
- Loan Type: {lead.get('loan_type_code', 'N/A')}
- Requested Amount: ₹{float(requested_amount):,.0f}
- Status: {lead.get('status_code', 'N/A')}
- Stage: {lead.get('stage', 'N/A')}""")
            
            # BRE recommendations
            if user_context.get("recommendations"):
                recs = user_context["recommendations"]
                rec_text = "\nLENDER RECOMMENDATIONS (from BRE):\n"
                for i, rec in enumerate(recs[:5], 1):
                    rec_text += f"""
{i}. {rec.get('lender_name', 'Unknown')} - {rec.get('product_name', '')}
   • Interest Rate: {rec.get('interest_rate', 'N/A')}%
   • EMI: ₹{rec.get('emi', 0):,.0f}/month
   • Amount: ₹{rec.get('amount', 0):,.0f}
   • Tenure: {rec.get('tenure', 0)} months
   • Processing Fee: ₹{rec.get('processing_fee', 0):,.0f}
   • Match Score: {rec.get('score', 0):.0f}/100"""
                blocks.append(rec_text)
        
        if context_type == "lender_selection":
            blocks.append("""
USER INTENT: Choosing from lender recommendations
- Help compare options based on their priorities
- Explain pros/cons of different choices
- Guide them to select via the dashboard""")
        
        return "\n".join(blocks) if blocks else "No specific user context available."
    
    def _generate_fallback_response(
        self,
        user_message: str,
        context_type: Optional[str],
        user_context: Optional[Dict[str, Any]],
    ) -> Tuple[str, str]:
        """Generate fallback response when OpenAI is not available."""
        message_lower = user_message.lower()
        
        # Check for greetings
        if any(word in message_lower for word in ["hi", "hello", "hey", "namaste", "good morning", "good evening"]):
            return "greeting", "Hello! Welcome to Roinet LMS. I'm here to help you with loan-related questions. How can I assist you today?"
        
        # Check for recommendation/lender selection queries
        if user_context and user_context.get("recommendations"):
            if any(word in message_lower for word in ["recommend", "choose", "select", "which", "best", "compare", "lender", "option"]):
                recs = user_context["recommendations"]
                response = "Here are your top recommendations:\n\n"
                for i, rec in enumerate(recs[:3], 1):
                    response += f"{i}. **{rec.get('lender_name')}**: {rec.get('interest_rate')}% p.a., EMI ₹{rec.get('emi', 0):,.0f}/mo\n"
                response += "\nConsider: lowest interest rate for savings, or shortest tenure for quick repayment. What's most important to you?"
                return "lender_help", response
        
        # Check against FAQ
        best_match = None
        best_score = 0
        
        for faq_id, faq in FAQ_DATA.items():
            score = sum(1 for keyword in faq["keywords"] if keyword in message_lower)
            if score > best_score:
                best_score = score
                best_match = faq
        
        if best_match and best_score >= 2:
            return "faq", best_match["answer"]
        
        # Context-specific responses
        if context_type == "lender_selection":
            return "lender_help", "I can help you choose a lender! Based on your profile, I'll explain each option. What factors matter most - lowest EMI, lowest interest rate, or fastest disbursement?"
        
        if context_type == "lead":
            return "lead_assistance", "I see you're working on a loan application. I can help with next steps, required documents, or answer questions about the process. What would you like to know?"
        
        # Default response
        return "unknown", "I'm here to help with your loan journey! I can assist with:\n• Loan eligibility and requirements\n• Document checklist\n• Interest rates and EMI\n• Comparing lender options\n\nWhat would you like to know?"
    
    def _detect_intent(self, user_message: str, response: str) -> str:
        """Detect the intent of the user's message."""
        message_lower = user_message.lower()
        
        if any(w in message_lower for w in ["hi", "hello", "hey"]):
            return "greeting"
        if any(w in message_lower for w in ["recommend", "choose", "select", "which lender", "best option"]):
            return "lender_selection"
        if any(w in message_lower for w in ["eligibility", "eligible", "qualify"]):
            return "eligibility_check"
        if any(w in message_lower for w in ["document", "upload", "kyc"]):
            return "document_help"
        if any(w in message_lower for w in ["status", "progress", "track"]):
            return "status_check"
        if any(w in message_lower for w in ["interest", "rate", "emi"]):
            return "rate_inquiry"
        if any(w in message_lower for w in ["apply", "start", "begin"]):
            return "application_help"
        
        return "general_query"
    
    async def _get_or_create_conversation(
        self,
        session_id: str,
        user_id: Optional[UUID],
        context_type: Optional[str],
        context_id: Optional[UUID],
        is_public: bool = False,
    ) -> ChatConversation:
        """Get existing active conversation or create a new one."""
        query = select(ChatConversation).where(
            and_(
                ChatConversation.session_id == session_id,
                ChatConversation.status == "ACTIVE",
            )
        )
        
        result = await self.db.execute(query)
        conversation = result.scalars().first()
        
        if not conversation:
            conversation = ChatConversation(
                session_id=session_id,
                user_id=user_id,
                context_type=context_type,
                context_id=context_id,
                is_public=is_public,
                status="ACTIVE",
            )
            self.db.add(conversation)
            await self.db.commit()
            await self.db.refresh(conversation)
        
        return conversation
    
    async def _get_recent_messages(
        self,
        conversation_id: UUID,
        limit: int = None,
    ) -> List[Dict[str, str]]:
        """Get recent messages for context."""
        limit = limit or settings.CHATBOT_MAX_HISTORY
        
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(result.scalars().all()))
        
        return [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
    
    async def _get_message_count(self, conversation_id: UUID) -> int:
        """Get total message count for a conversation."""
        result = await self.db.execute(
            select(func.count(ChatMessage.id))
            .where(ChatMessage.conversation_id == conversation_id)
        )
        return result.scalar() or 0
    
    async def get_conversation_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> Optional[ChatConversation]:
        """Get conversation with message history."""
        query = select(ChatConversation).where(
            and_(
                ChatConversation.session_id == session_id,
                ChatConversation.status == "ACTIVE",
            )
        )
        
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def end_conversation(self, session_id: str) -> bool:
        """End an active conversation."""
        query = select(ChatConversation).where(
            and_(
                ChatConversation.session_id == session_id,
                ChatConversation.status == "ACTIVE",
            )
        )
        
        result = await self.db.execute(query)
        conversation = result.scalars().first()
        
        if conversation:
            conversation.status = "CLOSED"
            conversation.ended_at = datetime.utcnow()
            await self.db.commit()
            return True
        
        return False
    
    async def get_public_session_info(self, session_id: str) -> Dict[str, Any]:
        """Get info about a public chat session (for rate limiting UI)."""
        query = select(ChatConversation).where(
            and_(
                ChatConversation.session_id == session_id,
                ChatConversation.is_public == True,
            )
        )
        
        result = await self.db.execute(query)
        conversation = result.scalars().first()
        
        if not conversation:
            return {
                "exists": False,
                "messages_used": 0,
                "messages_remaining": settings.PUBLIC_CHAT_MAX_MESSAGES,
            }
        
        message_count = await self._get_message_count(conversation.id)
        user_messages = message_count // 2  # Approximate user message count
        
        return {
            "exists": True,
            "session_id": session_id,
            "messages_used": user_messages,
            "messages_remaining": max(0, settings.PUBLIC_CHAT_MAX_MESSAGES - user_messages),
            "is_limit_reached": user_messages >= settings.PUBLIC_CHAT_MAX_MESSAGES,
        }
