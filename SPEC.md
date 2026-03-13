# LMS FinAI Service Specification

> **Version:** 1.0  
> **Date:** January 30, 2026  
> **Repository:** `lms-finai`  
> **Port:** 8007  
> **Database:** `lms_finai_db`

---

## Table of Contents

1. [Overview](#1-overview)
2. [Repository Structure](#2-repository-structure)
3. [Database Schema](#3-database-schema)
4. [API Endpoints](#4-api-endpoints)
5. [Chatbot (RAG)](#5-chatbot-rag)
6. [Voice Bot (Bolna)](#6-voice-bot-bolna)
7. [Configuration](#7-configuration)
8. [Docker Setup](#8-docker-setup)

---

## 1. Overview

### 1.1 Purpose

The FinAI Service provides AI-powered features:
- **Chatbot**: RAG-based FAQ and lead qualification
- **Voice Bot**: Bolna.ai integration for outbound calls
- **Campaigns**: Voice campaign management
- **Call Analytics**: Call transcription and analysis

### 1.2 Key Characteristics

| Aspect | Value |
|--------|-------|
| **Database** | PostgreSQL (`lms_finai_db`) |
| **AI Provider** | OpenAI (GPT), Whisper |
| **Voice Provider** | Bolna.ai |
| **RAG** | Vector store for knowledge base |

### 1.3 Features

| Feature | Status | Description |
|---------|--------|-------------|
| Chatbot FAQ | ✅ | Answer common questions |
| Lead Qualification | ✅ | Qualify leads via chat |
| Lender Selection | ✅ | Help choose from BRE results |
| Voice Campaigns | ✅ | Outbound call campaigns |
| Call Transcription | ✅ | Transcribe and analyze calls |

---

## 2. Repository Structure

```
lms-finai/
├── .github/
│   └── workflows/
│       ├── build.yml
│       └── deploy.yml
│
├── shared/
│   ├── __init__.py
│   ├── responses.py
│   ├── error_codes.py
│   └── constants.py
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── db.py
│   │   └── redis.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── chat_session.py
│   │   ├── campaign.py
│   │   └── call_log.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── chat.py
│   │   ├── campaign.py
│   │   └── call.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── api_v1/
│   │   │   ├── __init__.py
│   │   │   ├── chat.py
│   │   │   ├── voice.py
│   │   │   └── campaigns.py
│   │   │
│   │   └── internal/
│   │       ├── __init__.py
│   │       └── context.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chat/
│   │   │   ├── __init__.py
│   │   │   ├── chat_service.py
│   │   │   ├── rag_service.py
│   │   │   └── qualification_service.py
│   │   │
│   │   └── voice/
│   │       ├── __init__.py
│   │       ├── bolna_client.py
│   │       ├── campaign_service.py
│   │       └── call_analyzer.py
│   │
│   └── clients/
│       ├── __init__.py
│       ├── lead_ops_client.py
│       └── openai_client.py
│
├── knowledge_base/                 # RAG knowledge files
│   ├── faq.md
│   ├── loan_products.md
│   └── processes.md
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── init_db.sql
├── .env.example
└── README.md
```

---

## 3. Database Schema

### 3.1 Chat Sessions

```sql
-- Chat sessions
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- User
    user_id UUID,
    borrower_id UUID,
    phone VARCHAR(15),
    
    -- Session
    session_type VARCHAR(20) NOT NULL,  -- FAQ, QUALIFICATION, LENDER_SELECTION
    status VARCHAR(20) DEFAULT 'ACTIVE',  -- ACTIVE, COMPLETED, ABANDONED
    
    -- Context
    lead_id UUID,
    context JSONB,
    
    -- Timing
    started_at TIMESTAMP DEFAULT NOW(),
    last_message_at TIMESTAMP,
    ended_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Chat messages
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id),
    
    -- Message
    role VARCHAR(20) NOT NULL,  -- USER, ASSISTANT, SYSTEM
    content TEXT NOT NULL,
    
    -- Metadata
    intent VARCHAR(50),
    confidence DECIMAL(5,4),
    tokens_used INT,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_chat_sessions_user ON chat_sessions(user_id);
CREATE INDEX idx_chat_sessions_lead ON chat_sessions(lead_id);
CREATE INDEX idx_chat_messages_session ON chat_messages(session_id);
```

### 3.2 Campaigns

```sql
-- Voice campaigns
CREATE TABLE voice_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Campaign
    name VARCHAR(200) NOT NULL,
    description TEXT,
    campaign_type VARCHAR(50) NOT NULL,  -- QUALIFICATION, FOLLOW_UP, COLLECTION
    
    -- Target
    target_audience JSONB,  -- Filters for lead selection
    
    -- Script
    script_template TEXT NOT NULL,
    voice_id VARCHAR(100),
    
    -- Schedule
    scheduled_start TIMESTAMP,
    scheduled_end TIMESTAMP,
    
    -- Status
    status VARCHAR(20) DEFAULT 'DRAFT',
    -- DRAFT, SCHEDULED, RUNNING, PAUSED, COMPLETED, CANCELLED
    
    -- Stats
    total_leads INT DEFAULT 0,
    calls_made INT DEFAULT 0,
    calls_connected INT DEFAULT 0,
    qualified_count INT DEFAULT 0,
    
    -- Metadata
    created_by UUID NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Campaign leads
CREATE TABLE campaign_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES voice_campaigns(id),
    lead_id UUID NOT NULL,
    
    -- Contact
    phone VARCHAR(15) NOT NULL,
    
    -- Status
    status VARCHAR(20) DEFAULT 'PENDING',
    -- PENDING, SCHEDULED, CALLING, COMPLETED, FAILED, SKIPPED
    
    -- Result
    call_outcome VARCHAR(50),  -- CONNECTED, NO_ANSWER, BUSY, VOICEMAIL, FAILED
    is_qualified BOOLEAN,
    qualification_data JSONB,
    
    -- Timing
    scheduled_at TIMESTAMP,
    called_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_campaigns_status ON voice_campaigns(status);
CREATE INDEX idx_campaign_leads_campaign ON campaign_leads(campaign_id);
CREATE INDEX idx_campaign_leads_lead ON campaign_leads(lead_id);
CREATE INDEX idx_campaign_leads_status ON campaign_leads(status);
```

### 3.3 Call Logs

```sql
-- Call logs (from Bolna)
CREATE TABLE call_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Reference
    campaign_id UUID REFERENCES voice_campaigns(id),
    campaign_lead_id UUID REFERENCES campaign_leads(id),
    lead_id UUID,
    
    -- Bolna
    bolna_call_id VARCHAR(100) UNIQUE,
    
    -- Call Details
    phone_number VARCHAR(15) NOT NULL,
    direction VARCHAR(10) NOT NULL,  -- OUTBOUND, INBOUND
    
    -- Status
    status VARCHAR(20) NOT NULL,
    -- INITIATED, RINGING, CONNECTED, COMPLETED, FAILED, NO_ANSWER
    
    -- Timing
    initiated_at TIMESTAMP NOT NULL,
    connected_at TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INT,
    
    -- Recording
    recording_url TEXT,
    
    -- Transcription
    transcription TEXT,
    transcription_status VARCHAR(20),  -- PENDING, PROCESSING, COMPLETED, FAILED
    
    -- Analysis
    sentiment VARCHAR(20),  -- POSITIVE, NEUTRAL, NEGATIVE
    intent VARCHAR(50),
    key_points TEXT[],
    action_items TEXT[],
    
    -- Metadata
    metadata JSONB,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_calls_campaign ON call_logs(campaign_id);
CREATE INDEX idx_calls_lead ON call_logs(lead_id);
CREATE INDEX idx_calls_bolna ON call_logs(bolna_call_id);
CREATE INDEX idx_calls_status ON call_logs(status);
```

---

## 4. API Endpoints

### 4.1 Chat

```
POST   /api/v1/chat/sessions              → Start chat session
POST   /api/v1/chat/sessions/{id}/message → Send message
GET    /api/v1/chat/sessions/{id}         → Get session with messages
POST   /api/v1/chat/sessions/{id}/end     → End session
```

**Start Session Request:**
```json
POST /api/v1/chat/sessions
{
  "session_type": "LENDER_SELECTION",
  "lead_id": "uuid",
  "context": {
    "bre_results": [...]
  }
}
```

**Send Message Request:**
```json
POST /api/v1/chat/sessions/{id}/message
{
  "content": "Which lender has the lowest interest rate?"
}
```

**Message Response:**
```json
{
  "success": true,
  "data": {
    "message_id": "uuid",
    "role": "ASSISTANT",
    "content": "Based on your BRE results, HDFC Bank offers the lowest interest rate at 10.5% p.a. Would you like me to explain the other terms of their offer?",
    "suggestions": [
      "Tell me about HDFC's processing fee",
      "Compare all three lenders",
      "I want to select HDFC"
    ]
  }
}
```

### 4.2 Voice Campaigns

```
GET    /api/v1/campaigns                  → List campaigns
POST   /api/v1/campaigns                  → Create campaign
GET    /api/v1/campaigns/{id}             → Get campaign details
PATCH  /api/v1/campaigns/{id}             → Update campaign
POST   /api/v1/campaigns/{id}/start       → Start campaign
POST   /api/v1/campaigns/{id}/pause       → Pause campaign
POST   /api/v1/campaigns/{id}/cancel      → Cancel campaign

GET    /api/v1/campaigns/{id}/leads       → Get campaign leads
POST   /api/v1/campaigns/{id}/leads       → Add leads to campaign
```

**Create Campaign Request:**
```json
POST /api/v1/campaigns
{
  "name": "January Follow-up Campaign",
  "campaign_type": "FOLLOW_UP",
  "description": "Follow up on leads that haven't selected a lender",
  "target_audience": {
    "status": "BRE_ELIGIBLE",
    "created_after": "2026-01-01",
    "region_code": "NORTH"
  },
  "script_template": "Hello {{name}}, this is Roinet calling about your loan application...",
  "scheduled_start": "2026-01-31T09:00:00Z"
}
```

### 4.3 Call Logs

```
GET    /api/v1/voice/calls                → List calls
GET    /api/v1/voice/calls/{id}           → Get call details
GET    /api/v1/voice/calls/{id}/recording → Get recording URL
GET    /api/v1/voice/calls/{id}/transcript → Get transcription
```

### 4.4 Bolna Webhook

```
POST   /api/v1/voice/webhook/bolna        → Bolna callback webhook
```

---

## 5. Chatbot (RAG)

### 5.1 RAG Service

```python
# app/services/chat/rag_service.py
from openai import AsyncOpenAI


class RAGService:
    """RAG-based chatbot service."""
    
    def __init__(self, settings):
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.knowledge_base = self._load_knowledge_base()
    
    def _load_knowledge_base(self) -> str:
        """Load knowledge base documents."""
        knowledge = ""
        for file in ["faq.md", "loan_products.md", "processes.md"]:
            with open(f"knowledge_base/{file}") as f:
                knowledge += f"\n\n# {file}\n{f.read()}"
        return knowledge
    
    async def get_response(
        self,
        session: ChatSession,
        user_message: str,
        context: dict = None
    ) -> str:
        """Get AI response for user message."""
        
        # Build system prompt
        system_prompt = f"""You are a helpful loan assistant for Roinet LMS.
        
Knowledge Base:
{self.knowledge_base}

Session Context:
- Type: {session.session_type}
- Lead ID: {session.lead_id}
{f"- BRE Results: {context.get('bre_results')}" if context else ""}

Guidelines:
- Be helpful and professional
- If asked about lender selection, use the BRE results in context
- For FAQs, use the knowledge base
- If unsure, say you'll connect them with a human agent
- Keep responses concise (under 100 words)
"""
        
        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history
        for msg in session.messages[-10:]:  # Last 10 messages
            messages.append({"role": msg.role.lower(), "content": msg.content})
        
        messages.append({"role": "user", "content": user_message})
        
        # Get response
        response = await self.openai.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )
        
        return response.choices[0].message.content
```

### 5.2 Lender Selection Helper

```python
# app/services/chat/qualification_service.py
class LenderSelectionService:
    """Help users select a lender from BRE results."""
    
    async def compare_lenders(self, bre_results: list) -> str:
        """Generate comparison summary."""
        
        if not bre_results:
            return "No eligible lenders found for your application."
        
        # Sort by rank
        sorted_results = sorted(bre_results, key=lambda x: x.get("rank", 999))
        
        comparison = "Here's a comparison of your options:\n\n"
        
        for i, lender in enumerate(sorted_results[:3], 1):
            comparison += f"{i}. **{lender['lender_name']}**\n"
            comparison += f"   - Interest Rate: {lender['interest_rate']}% p.a.\n"
            comparison += f"   - Loan Amount: ₹{lender['offered_amount']:,.0f}\n"
            comparison += f"   - EMI: ₹{lender['emi']:,.0f}/month\n"
            comparison += f"   - Processing Fee: ₹{lender['processing_fee']:,.0f}\n\n"
        
        comparison += "Would you like more details about any of these options?"
        
        return comparison
    
    async def select_lender(
        self,
        lead_id: UUID,
        lender_product_id: UUID,
        lead_ops_client
    ) -> dict:
        """Select a lender for the lead."""
        
        result = await lead_ops_client.select_lender(lead_id, lender_product_id)
        
        if result.get("success"):
            return {
                "success": True,
                "message": f"Great! I've selected {result['data']['lender_name']} for you. Your application will now be processed."
            }
        else:
            return {
                "success": False,
                "message": "I couldn't process your selection. Please try again or contact support."
            }
```

---

## 6. Voice Bot (Bolna)

### 6.1 Bolna Client

```python
# app/services/voice/bolna_client.py
import httpx
from typing import Dict, Any


class BolnaClient:
    """Client for Bolna.ai voice API."""
    
    def __init__(self, settings):
        self.base_url = settings.BOLNA_BASE_URL
        self.api_key = settings.BOLNA_API_KEY
        self.agent_id = settings.BOLNA_AGENT_ID
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def initiate_call(
        self,
        phone_number: str,
        script_variables: Dict[str, str],
        webhook_url: str
    ) -> Dict[str, Any]:
        """Initiate an outbound call."""
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/calls",
                headers=self._get_headers(),
                json={
                    "agent_id": self.agent_id,
                    "phone_number": phone_number,
                    "variables": script_variables,
                    "webhook_url": webhook_url
                }
            )
            return response.json()
    
    async def get_call_status(self, call_id: str) -> Dict[str, Any]:
        """Get call status and details."""
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/calls/{call_id}",
                headers=self._get_headers()
            )
            return response.json()
    
    async def get_recording(self, call_id: str) -> str:
        """Get call recording URL."""
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/calls/{call_id}/recording",
                headers=self._get_headers()
            )
            return response.json().get("recording_url")
    
    async def get_transcription(self, call_id: str) -> str:
        """Get call transcription."""
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/calls/{call_id}/transcription",
                headers=self._get_headers()
            )
            return response.json().get("transcription")
```

### 6.2 Campaign Runner

```python
# app/services/voice/campaign_service.py
class CampaignRunner:
    """Run voice campaigns."""
    
    async def run_campaign(self, campaign_id: UUID):
        """Execute a campaign."""
        
        campaign = await self.campaign_repo.get(campaign_id)
        
        if campaign.status != "RUNNING":
            return
        
        # Get pending leads
        leads = await self.campaign_lead_repo.get_pending(campaign_id, limit=10)
        
        for lead in leads:
            # Check time window (9 AM - 6 PM)
            if not self._is_calling_hours():
                break
            
            # Prepare variables for script
            lead_data = await self.lead_ops_client.get_lead(lead.lead_id)
            variables = {
                "name": lead_data.get("borrower_name", "Sir/Madam"),
                "loan_type": lead_data.get("loan_type_code"),
                "amount": str(lead_data.get("requested_amount", ""))
            }
            
            # Initiate call
            try:
                result = await self.bolna.initiate_call(
                    phone_number=lead.phone,
                    script_variables=variables,
                    webhook_url=f"{self.webhook_base_url}/voice/webhook/bolna"
                )
                
                # Update lead status
                await self.campaign_lead_repo.update(
                    lead.id,
                    status="CALLING",
                    called_at=datetime.utcnow()
                )
                
                # Create call log
                await self.call_log_repo.create(
                    campaign_id=campaign_id,
                    campaign_lead_id=lead.id,
                    lead_id=lead.lead_id,
                    bolna_call_id=result.get("call_id"),
                    phone_number=lead.phone,
                    direction="OUTBOUND",
                    status="INITIATED",
                    initiated_at=datetime.utcnow()
                )
                
            except Exception as e:
                logger.error(f"Failed to initiate call: {e}")
                await self.campaign_lead_repo.update(
                    lead.id,
                    status="FAILED"
                )
    
    def _is_calling_hours(self) -> bool:
        """Check if within calling hours (9 AM - 6 PM IST)."""
        now = datetime.now(timezone("Asia/Kolkata"))
        return 9 <= now.hour < 18
```

### 6.3 Webhook Handler

```python
# app/routers/api_v1/voice.py
@router.post("/webhook/bolna")
async def bolna_webhook(request: Request):
    """Handle Bolna call status webhook."""
    
    data = await request.json()
    call_id = data.get("call_id")
    event = data.get("event")
    
    call_log = await call_log_repo.get_by_bolna_id(call_id)
    if not call_log:
        return {"status": "ignored"}
    
    if event == "call.connected":
        await call_log_repo.update(
            call_log.id,
            status="CONNECTED",
            connected_at=datetime.utcnow()
        )
    
    elif event == "call.completed":
        # Get recording and transcription
        recording_url = await bolna.get_recording(call_id)
        transcription = await bolna.get_transcription(call_id)
        
        # Analyze call
        analysis = await call_analyzer.analyze(transcription)
        
        await call_log_repo.update(
            call_log.id,
            status="COMPLETED",
            ended_at=datetime.utcnow(),
            duration_seconds=data.get("duration"),
            recording_url=recording_url,
            transcription=transcription,
            sentiment=analysis.sentiment,
            intent=analysis.intent,
            key_points=analysis.key_points
        )
        
        # Update campaign lead
        await campaign_lead_repo.update(
            call_log.campaign_lead_id,
            status="COMPLETED",
            call_outcome="CONNECTED",
            is_qualified=analysis.is_qualified,
            qualification_data=analysis.to_dict()
        )
    
    elif event == "call.failed":
        await call_log_repo.update(
            call_log.id,
            status="FAILED",
            ended_at=datetime.utcnow()
        )
    
    return {"status": "ok"}
```

### 6.4 Multi-provider Telephony Gateway (Twilio/Plivo/Exotel/FreeSWITCH)

The service also includes a **pluggable telephony gateway** that can run the same AI voice agent
across multiple providers (cloud telephony + SIP gateway).

Key building blocks:

- `AgentProfile` (DB): dynamic prompt + pipeline config (realtime provider/model, audio codecs, language, voice id)
- `/api/v1/agents/*`: CRUD for agent profiles (your frontend can change prompts at runtime)
- `/api/v1/telephony/*`: provider registry + outbound call trigger + streaming WebSocket endpoints

Core endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/telephony/providers` | list registered providers and whether configured |
| `POST /api/v1/telephony/outbound` | start an outbound call via selected provider |
| `WS /api/v1/telephony/twilio/ws` | Twilio Media Streams (bi-directional) |
| `WS /api/v1/telephony/plivo/ws` | Plivo WS streaming |
| `WS /api/v1/telephony/exotel/ws` | Exotel AgentStream WS streaming |
| `WS /api/v1/telephony/freeswitch/ws` | FreeSWITCH WS streaming (see below) |

Realtime audio-to-audio is handled by an internal bridge:

- OpenAI Realtime (default): connects to `wss://api.openai.com/v1/realtime`.
- Local (open-source) A2A gateway (optional): set `LOCAL_A2A_WS_URL` to any **OpenAI Realtime compatible** websocket server.

### 6.5 FreeSWITCH SIP Gateway Blueprint (Option 2)

FreeSWITCH is recommended when you want SIP trunking / on-prem dialer control.

Supported approaches:

1) **mod_audio_stream** (recommended):
   - community edition: caller audio -> WS (uni-directional)
   - commercial edition (free up to 10 channels): full duplex + raw binary mode

2) **mod_twilio_stream**: emits Twilio-like JSON messages to a WebSocket.
   - You can point it directly at the service's `WS /api/v1/telephony/twilio/ws`.

Minimal dialplan example (mod_audio_stream):

```xml
<extension name="voice_agent">
  <condition field="destination_number" expression="^9999$">
    <action application="set" data="STREAM_SAMPLE_RATE=16000"/>
    <action application="set" data="STREAM_PLAYBACK=true"/>
    <!-- on answer, stream audio to your app WS endpoint -->
    <action application="set" data="api_on_answer=uuid_audio_stream ${uuid} start wss://YOUR_PUBLIC_WS/api/v1/telephony/freeswitch/ws mono 16k {\"agent_profile_id\":\"<UUID>\"}"/>
    <action application="answer"/>
    <action application="park"/>
  </condition>
</extension>
```

Outbound originate (from this service):

- Configure `FREESWITCH_ESL_HOST`, `FREESWITCH_ESL_PASSWORD` (and optionally `FREESWITCH_SIP_GATEWAY`).
- Call `POST /api/v1/telephony/outbound` with `provider="freeswitch"`.

Environment variables (examples):

```bash
TELEPHONY_PUBLIC_WS_BASE=wss://your-domain
FREESWITCH_ESL_HOST=10.0.0.10
FREESWITCH_ESL_PORT=8021
FREESWITCH_ESL_PASSWORD=ClueCon
FREESWITCH_SOFIA_PROFILE=external
FREESWITCH_SIP_GATEWAY=my_trunk_gateway
FREESWITCH_STREAM_SAMPLE_RATE=16000
```

Important notes:

- For **raw-binary mode** (best latency), ensure sample rates match on both sides.
- When using Twilio-like JSON mode, use `g711_ulaw` (PCMU) for 8 kHz telephony.
- Your SIP trunking + dialplan will determine caller-id, codecs, and routing.

---

## 7. Configuration

### 7.1 Environment Variables

```bash
# .env.example

HOST=0.0.0.0
PORT=8007
DEBUG=false

DATABASE_URL=postgresql+asyncpg://lms_finai:password@postgres:5432/lms_finai_db
REDIS_URL=redis://redis:6379/1

LEAD_OPS_SERVICE_URL=http://lead-ops:8003
IDENTITY_SERVICE_URL=http://identity:8001

SERVICE_CLIENT_ID=finai-service
SERVICE_CLIENT_SECRET=finai-secret-key

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4-turbo-preview

# Bolna
BOLNA_BASE_URL=https://api.bolna.ai/v1
BOLNA_API_KEY=your-bolna-api-key
BOLNA_AGENT_ID=your-agent-id
BOLNA_WEBHOOK_URL=https://api.yourdomain.com/api/v1/voice/webhook/bolna

# Campaign Settings
CAMPAIGN_CALLING_HOURS_START=9
CAMPAIGN_CALLING_HOURS_END=18
CAMPAIGN_MAX_CONCURRENT_CALLS=5
```

---

## 8. Docker Setup

### 8.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY app/ /app/app/
COPY knowledge_base/ /app/knowledge_base/

EXPOSE 8007
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
```

### 8.2 requirements.txt

```
fastapi==0.109.0
uvicorn==0.27.0
sqlalchemy==2.0.25
asyncpg==0.29.0
pydantic-settings==2.1.0
httpx==0.26.0
python-jose[cryptography]==3.3.0
openai==1.10.0
redis==5.0.1
```

---

## Summary

| Feature | Implementation |
|---------|----------------|
| **Chatbot** | RAG with GPT-4, knowledge base |
| **Lead Qualification** | Chat-based qualification |
| **Lender Selection** | Interactive comparison, selection |
| **Voice Campaigns** | Bolna.ai integration |
| **Call Analytics** | Transcription, sentiment, intent |

**Database Tables: 5**

---

**End of FinAI Service Specification**
