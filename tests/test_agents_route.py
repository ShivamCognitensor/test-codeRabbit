from uuid import UUID, uuid4
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.models.agent_profile import AgentProfile
from app.clients.voicebot_client import VoicebotClientError

client = TestClient(app)

# --- Fake in-memory DB session ---
class FakeResult:
    def __init__(self, items):
        self._items = items
    def scalars(self):
        class S:
            def __init__(self, items):
                self._items = items
            def all(self):
                return list(self._items)
        return S(self._items)

class FakeAsyncSession:
    def __init__(self):
        self._store = {}
    async def execute(self, stmt):
        # return all items ordered by created_at desc
        items = sorted(self._store.values(), key=lambda x: getattr(x, "created_at", 0), reverse=True)
        return FakeResult(items)
    def add(self, obj):
        self._store[obj.id] = obj
    async def commit(self):
        return None
    async def refresh(self, obj):
        return None
    async def get(self, model, id_):
        return self._store.get(id_)
    async def delete(self, obj):
        self._store.pop(obj.id, None)

# Dependency overrides
fake_db = FakeAsyncSession()

def override_get_db():
    return fake_db

def override_get_current_user():
    return {"sub": "test-user"}

# require_permission dependency in this project returns a dependency callable; override by a no-op
from app.routers import agents as agents_router_module

app.dependency_overrides[agents_router_module.get_db] = override_get_db
app.dependency_overrides[agents_router_module.get_current_user] = override_get_current_user
app.dependency_overrides[agents_router_module.require_permission("voicebot.view")] = lambda: None
app.dependency_overrides[agents_router_module.require_permission("voicebot.manage")] = lambda: None

# Helper to create AgentProfile instances
def make_agent(name="a", **kwargs):
    a = AgentProfile(
        id=uuid4(),
        name=name,
        description=kwargs.get("description"),
        language=kwargs.get("language", "en"),
        system_prompt=kwargs.get("system_prompt", None),
        prompt_template=kwargs.get("prompt_template", None),
        pipeline_config=kwargs.get("pipeline_config", None),
        voice_config=kwargs.get("voice_config", None),
        analytics_config=kwargs.get("analytics_config", None),
        is_active=kwargs.get("is_active", True),
    )
    return a

@pytest.fixture(autouse=True)
def reset_store():
    # reset fake DB store for each test
    fake_db._store = {}
    yield

def test_list_agents_empty():
    r = client.get("/api/v1/agents")
    assert r.status_code == 200
    assert isinstance(r.json().get("data"), list)
    assert r.json()["data"] == []

def test_create_agent_and_get():
    payload = {
        "name": "TestAgent",
        "description": "desc",
        "language": "en",
        "system_prompt": None,
        "prompt_template": None,
        "pipeline_config": None,
        "voice_config": None,
        "analytics_config": None,
        "is_active": True,
    }
    r = client.post("/api/v1/agents", json=payload)
    assert r.status_code == 201
    data = r.json().get("data")
    assert data["name"] == "TestAgent"

    # fetch list should include it
    r2 = client.get("/api/v1/agents")
    assert r2.status_code == 200
    assert any(x["name"] == "TestAgent" for x in r2.json().get("data", []))

def test_get_nonexistent_agent_returns_404():
    r = client.get(f"/api/v1/agents/{uuid4()}")
    assert r.status_code == 404

def test_update_agent():
    # insert an agent into fake store
    a = make_agent(name="old")
    fake_db._store[a.id] = a

    payload = {"name": "new-name"}
    r = client.put(f"/api/v1/agents/{a.id}", json=payload)
    assert r.status_code == 200
    data = r.json().get("data")
    assert data["name"] == "new-name"

def test_delete_agent():
    a = make_agent(name="todel")
    fake_db._store[a.id] = a
    r = client.delete(f"/api/v1/agents/{a.id}")
    assert r.status_code == 200
    assert r.json().get("data") == {"deleted": True}
    # ensure gone
    r2 = client.get(f"/api/v1/agents/{a.id}")
    assert r2.status_code == 404


# --- New tests for pipeline_config normalization ---

@patch("app.routers.agents.VoicebotClient.from_settings")
def test_create_agent_with_local_voicebot_combo_normalizes_pipeline_config(mock_from_settings):
    """Should normalize pipeline_config with local realtime provider and voicebot_combo."""
    # Mock VoicebotClient to return a stack_id
    mock_client = AsyncMock()
    mock_client.create_stack = AsyncMock(return_value="test-stack-123")
    mock_from_settings.return_value = mock_client

    payload = {
        "name": "LocalAgent",
        "description": "Agent with local models",
        "language": "en",
        "pipeline_config": {
            "realtime_provider": "local",
            "voicebot_combo": {
                "stt_id": "whisper-1",
                "llm_id": "llama-3",
                "tts_id": "coqui-1"
            }
        },
        "is_active": True,
    }
    
    r = client.post("/api/v1/agents", json=payload)
    assert r.status_code == 201
    data = r.json().get("data")
    assert data["name"] == "LocalAgent"
    assert "pipeline_config" in data
    assert data["pipeline_config"]["voicebot_stack_id"] == "test-stack-123"
    
    # Verify create_stack was called with correct params
    mock_client.create_stack.assert_called_once()
    call_kwargs = mock_client.create_stack.call_args.kwargs
    assert call_kwargs["stt_id"] == "whisper-1"
    assert call_kwargs["llm_id"] == "llama-3"
    assert call_kwargs["tts_id"] == "coqui-1"


def test_create_agent_with_missing_stt_id_returns_400():
    """Should return 400 when voicebot_combo is missing required stt_id."""
    payload = {
        "name": "InvalidAgent",
        "description": "Missing stt_id",
        "language": "en",
        "pipeline_config": {
            "realtime_provider": "local",
            "voicebot_combo": {
                "tts_id": "coqui-1"
                # missing stt_id
            }
        },
        "is_active": True,
    }
    
    r = client.post("/api/v1/agents", json=payload)
    assert r.status_code == 400
    assert "voicebot_combo requires stt_id and tts_id" in r.json().get("detail", "")


def test_create_agent_with_missing_tts_id_returns_400():
    """Should return 400 when voicebot_combo is missing required tts_id."""
    payload = {
        "name": "InvalidAgent",
        "description": "Missing tts_id",
        "language": "en",
        "pipeline_config": {
            "realtime_provider": "local",
            "voicebot_combo": {
                "stt_id": "whisper-1"
                # missing tts_id
            }
        },
        "is_active": True,
    }
    
    r = client.post("/api/v1/agents", json=payload)
    assert r.status_code == 400
    assert "voicebot_combo requires stt_id and tts_id" in r.json().get("detail", "")


@patch("app.routers.agents.VoicebotClient.from_settings")
def test_create_agent_voicebot_client_error_returns_502(mock_from_settings):
    """Should return 502 when VoicebotClient raises VoicebotClientError."""
    # Mock VoicebotClient to raise VoicebotClientError
    mock_client = AsyncMock()
    mock_client.create_stack = AsyncMock(side_effect=VoicebotClientError("Service unavailable"))
    mock_from_settings.return_value = mock_client

    payload = {
        "name": "FailingAgent",
        "description": "Voicebot service error",
        "language": "en",
        "pipeline_config": {
            "realtime_provider": "local",
            "voicebot_combo": {
                "stt_id": "whisper-1",
                "tts_id": "coqui-1"
            }
        },
        "is_active": True,
    }
    
    r = client.post("/api/v1/agents", json=payload)
    assert r.status_code == 502
    assert "Service unavailable" in r.json().get("detail", "")


@patch("app.routers.agents.VoicebotClient.from_settings")
def test_create_agent_unexpected_error_returns_500(mock_from_settings):
    """Should return 500 when VoicebotClient raises unexpected exception."""
    # Mock VoicebotClient to raise generic Exception
    mock_client = AsyncMock()
    mock_client.create_stack = AsyncMock(side_effect=Exception("Unexpected error"))
    mock_from_settings.return_value = mock_client

    payload = {
        "name": "UnexpectedErrorAgent",
        "description": "Unexpected error",
        "language": "en",
        "pipeline_config": {
            "realtime_provider": "local",
            "voicebot_combo": {
                "stt_id": "whisper-1",
                "tts_id": "coqui-1"
            }
        },
        "is_active": True,
    }
    
    r = client.post("/api/v1/agents", json=payload)
    assert r.status_code == 500
    assert "Unexpected error" in r.json().get("detail", "")


@patch("app.routers.agents.VoicebotClient.from_settings")
def test_update_agent_normalizes_pipeline_config(mock_from_settings):
    """Should handle pipeline_config normalization during agent update."""
    # Mock VoicebotClient to return a stack_id
    mock_client = AsyncMock()
    mock_client.create_stack = AsyncMock(return_value="updated-stack-456")
    mock_from_settings.return_value = mock_client

    # Create an agent first
    a = make_agent(name="ToUpdate")
    fake_db._store[a.id] = a

    # Update with local voicebot_combo
    payload = {
        "pipeline_config": {
            "realtime_provider": "local",
            "voicebot_combo": {
                "stt_id": "whisper-2",
                "tts_id": "coqui-2"
            }
        }
    }
    
    r = client.put(f"/api/v1/agents/{a.id}", json=payload)
    assert r.status_code == 200
    data = r.json().get("data")
    assert "pipeline_config" in data
    assert data["pipeline_config"]["voicebot_stack_id"] == "updated-stack-456"
    
    # Verify create_stack was called
    mock_client.create_stack.assert_called_once()
    call_kwargs = mock_client.create_stack.call_args.kwargs
    assert call_kwargs["stt_id"] == "whisper-2"
    assert call_kwargs["tts_id"] == "coqui-2"
