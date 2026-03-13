# Roinet LMS - FinAI Service

AI-powered chatbot and voice bot service for loan assistance and customer support.

## Features

- **AI Chatbot**
  - Loan product recommendations
  - Eligibility guidance
  - FAQ assistance
  - Contextual conversations with lead data
- **Voice Bot (Bolna.ai)**
  - Outbound calling campaigns
  - Lead qualification calls
  - Webhook handling
- **Multi-provider Telephony**
  - Twilio / Plivo / Exotel / SIP gateway adapters
  - WebSocket streaming endpoints for live calls
- **Open-source Voice Stack (Optional)**
  - Local Realtime gateway: WS `/v1/realtime` (OpenAI-Realtime compatible)
  - STT: Whisper v3 Turbo or Canary Qwen (optional)
  - TTS: Kokoro (CPU) or Fish Speech server
- **Knowledge Base (RAG)**
  - Product information retrieval
  - FAQ matching
- **Public Chat** (Unauthenticated)
  - Limited messages per session
  - Rate limiting
  - No PII collection

## Tech Stack

- **Framework**: FastAPI
- **AI**: OpenAI GPT-4o-mini
- **Voice**: Bolna.ai
- **Database**: PostgreSQL (async)
- **Embeddings**: OpenAI text-embedding-3-small

## Quick Start

### Prerequisites
- Python 3.12+
- PostgreSQL 15+
- OpenAI API key
- Bolna.ai API key (for voice bot)

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/tech-cognitensor/roinet-lms-finai.git
cd roinet-lms-finai
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Setup environment:
```bash
cp .env.example .env
# Add your OPENAI_API_KEY and BOLNA_API_KEY
```

5. Run migrations:
```bash
alembic upgrade head
```

6. Build knowledge base index:
```bash
python -c "from app.services.kb_service import kb_service; kb_service.build_index()"
```

7. Run the service:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8007 --reload
```

## API Documentation

- **Swagger UI**: http://localhost:8007/docs

## Key Endpoints

### Chatbot (Authenticated)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat` | Send chat message |
| GET | `/api/v1/chat/history` | Get chat history |
| DELETE | `/api/v1/chat/history` | Clear history |

### Public Chat (Unauthenticated)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/public/chat` | Public chat (limited) |
| GET | `/api/v1/public/chat/session` | Get session info |

### Voice Bot
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/voice/call` | Initiate call |
| GET | `/api/v1/voice/call/{id}` | Get call status |
| POST | `/api/v1/voice/webhook` | Bolna webhook |

### Campaigns
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/campaigns` | Create campaign |
| GET | `/api/v1/campaigns` | List campaigns |
| POST | `/api/v1/campaigns/{id}/start` | Start campaign |
| POST | `/api/v1/campaigns/{id}/pause` | Pause campaign |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | Required |
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `OPENAI_CHAT_MODEL` | Chat model | `gpt-4o-mini` |
| `BOLNA_API_KEY` | Bolna.ai API key | Required for voice |
| `BOLNA_API_BASE` | Bolna API URL | `https://api.bolna.ai` |
| `KB_ENABLED` | Enable knowledge base | `true` |
| `KB_DOCS_PATH` | KB documents folder | `./kb_docs` |
| `PUBLIC_CHAT_ENABLED` | Enable public chat | `true` |
| `PUBLIC_CHAT_MAX_MESSAGES` | Messages per session | `10` |
| `PUBLIC_CHAT_RATE_LIMIT` | Requests per minute | `20` |

## Chatbot Features

### Contextual Chat
When authenticated, the chatbot can access:
- User's leads and their status
- Borrower profile information
- BRE results and eligible lenders
- Personalized recommendations

### Public Chat
- No authentication required
- Limited to 10 messages per session
- Rate limited (20 req/min per IP)
- No PII collection
- General loan information only

## Knowledge Base

Place documents in `kb_docs/` folder:
- Product information PDFs
- FAQ documents
- Policy documents

The system will:
1. Parse and chunk documents
2. Generate embeddings
3. Store in FAISS index
4. Retrieve relevant chunks for RAG

## Voice Bot (Bolna.ai)

### Supported Features
- Outbound calls
- Call status tracking
- Webhook events
- Campaign management

### Campaign Structure
```json
{
  "name": "Lead Follow-up",
  "agent_id": "bolna-agent-id",
  "contacts": [
    {"phone": "+919876543210", "name": "John", "lead_id": "uuid"}
  ],
  "schedule": {
    "start_time": "09:00",
    "end_time": "18:00",
    "timezone": "Asia/Kolkata"
  }
}
```

## Project Structure

```
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── auth.py
│   │   └── rate_limiter.py
│   ├── models/
│   │   ├── conversation.py
│   │   └── campaign.py
│   ├── routers/
│   │   ├── chatbot.py
│   │   ├── public_chat.py
│   │   ├── voice.py
│   │   └── campaigns.py
│   ├── services/
│   │   ├── chatbot_service.py
│   │   ├── kb_service.py
│   │   └── voice_service.py
│   └── clients/
│       ├── openai_client.py
│       └── bolna_client.py
├── kb_docs/                 # Knowledge base documents
├── kb_index/                # FAISS index (generated)
├── alembic/
├── shared/
├── postman/
└── README.md
```

## Related Repositories

- [lms-shared](https://github.com/tech-cognitensor/roinet-lms-shared) - Shared utilities
- [lms-lead-ops](https://github.com/tech-cognitensor/roinet-lms-lead-ops) - Lead context

## License

Proprietary - Cognitensor Technologies Pvt. Ltd.
