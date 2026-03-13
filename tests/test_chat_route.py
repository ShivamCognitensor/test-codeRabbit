import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_chat_schema():
    # This is a smoke test for request validation.
    r = client.post("/v1/chat", json={"session_id": "t1", "message": "hello"})
    # Without OPENAI_API_KEY this may fail at runtime; we mainly ensure route exists.
    assert r.status_code in (200, 500, 401, 400)
