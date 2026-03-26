"""UI catalog endpoints.

The frontend should not hardcode local model lists. Instead, it should call
this endpoint and render the options returned by the backend.

Flow:
  Frontend -> LMS (/api/v1/ui/model-catalog)
    LMS -> Voicebot Service (/v1/catalog) over private VPC networking
"""

from __future__ import annotations
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import httpx
from app.clients.voicebot_client import VoicebotClient, VoicebotClientError
from app.core.auth import get_current_user, require_permission
from shared.responses import success_response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ui", tags=["UI"])


def _basename_if_path(value: str) -> str:
    """
    Convert absolute/local path -> basename.
    If value doesn't look like a path, return as-is.
    """
    if not isinstance(value, str):
        return value
    # Very simple heuristic: treat anything containing "/" as a path
    if "/" in value:
        return os.path.basename(value.rstrip("/"))
    return value

def _normalize_catalog_payload(raw: Any) -> Dict[str, Any]:
    """
    Normalize voicebot catalog response into a stable shape:
      {"providers": [...], "local": {"stt_models":..., "llm_models":..., "tts_models":..., "stacks":...}}
    Supports:
      - full wrapper {success, message, ...}
      - message-only {providers, local}
      - local-only {stt_models, llm_models, tts_models, stacks}
    """
    if not isinstance(raw, dict):
        return {"providers": ["openai", "bolna", "local"], "local": {}}

    # Unwrap full wrapper
    if isinstance(raw.get("message"), dict):
        raw = raw["message"]

    # If already message-only shape
    if "local" in raw and isinstance(raw.get("local"), dict):
        return {
            "providers": raw.get("providers") or ["openai", "bolna", "local"],
            "local": raw["local"],
        }

    # If local-only shape
    if any(k in raw for k in ("stt_models", "llm_models", "tts_models", "stacks")):
        return {
            "providers": ["openai", "bolna", "local"],
            "local": raw,
        }

    # Fallback
    return {"providers": ["openai", "bolna", "local"], "local": {}}

def _extract_languages_from_models(models: Dict[str, Any]) -> List[str]:
    # stt models often like {"en": "/path", "hi": "/path"}
    langs: List[str] = []
    for k in (models or {}).keys():
        if isinstance(k, str):
            langs.append(k)
    return sorted(langs)


def sanitize_voicebot_catalog(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove filesystem paths and internal config from Voicebot catalog.
    Keeps only UI-safe fields.
    """
    
    local = raw.get("local", {}) if isinstance(raw, dict) else {}

    stt_models_out: List[Dict[str, Any]] = []
    for m in local.get("stt_models", []) or []:
        models = m.get("models") or {}
        stt_models_out.append(
            {
                "id": m.get("id"),
                "label": m.get("label") or m.get("id"),
                "type": m.get("type"),
                "languages": _extract_languages_from_models(models),
            }
        )

    llm_models_out: List[Dict[str, Any]] = []
    for m in local.get("llm_models", []) or []:
        llm_models_out.append(
            {
                "id": m.get("id"),
                "label": m.get("label") or m.get("id"),
                "type": m.get("type"),
                "model_name": _basename_if_path(m.get("model", "")),
            }
        )

    tts_models_out: List[Dict[str, Any]] = []
    for m in local.get("tts_models", []) or []:
        tts_type = m.get("type")
        if tts_type == "piper":
            voices = m.get("voices") or {}
            tts_models_out.append(
                {
                    "id": m.get("id"),
                    "label": m.get("label") or m.get("id"),
                    "type": "piper",
                    "voices": sorted([str(k) for k in voices.keys()]),
                }
            )
        elif tts_type == "indic_parler":
            tts_models_out.append(
                {
                    "id": m.get("id"),
                    "label": m.get("label") or m.get("id"),
                    "type": "indic_parler",
                    "model": m.get("model") or m.get("model_id") or "indic-parler-tts",
                    "device": m.get("device", "cpu"),
                }
            )
        else:
            # fallback
            tts_models_out.append(
                {
                    "id": m.get("id"),
                    "label": m.get("label") or m.get("id"),
                    "type": tts_type,
                }
            )

    stacks_out: List[Dict[str, Any]] = []
    for s in local.get("stacks", []) or []:
        stt = s.get("stt") or {}
        llm = s.get("llm") or {}
        tts = s.get("tts") or {}

        stacks_out.append(
            {
                "stack_id": s.get("stack_id"),
                "label": s.get("label") or s.get("stack_id"),
                "stt_id": s.get("stt_id"),
                "llm_id": s.get("llm_id"),
                "tts_id": s.get("tts_id"),
                "stt": {
                    "type": stt.get("type"),
                    "languages": _extract_languages_from_models(stt.get("models") or {}),
                },
                "llm": {
                    "type": llm.get("type"),
                    "model_name": _basename_if_path(llm.get("model", "")),
                },
                "tts": {
                    "type": tts.get("type"),
                    "voices": sorted([str(k) for k in (tts.get("voices") or {}).keys()]) if tts.get("type") == "piper" else None,
                    "device": tts.get("device") if tts.get("type") == "indic_parler" else None,
                    "model": tts.get("model") if tts.get("type") == "indic_parler" else None,
                },
            }
        )

    return {
        "providers": raw.get("providers", ["openai", "bolna", "local"]),
        "local": {
            "stt_models": stt_models_out,
            "llm_models": llm_models_out,
            "tts_models": tts_models_out,
            "stacks": stacks_out,
        },
    }


@router.get("/model-catalog", dependencies=[Depends(require_permission("voicebot.view"))])
async def model_catalog(user=Depends(get_current_user)):
    """Return available providers + local model catalog for the UI."""
    try:
        voicebot = VoicebotClient.from_settings()
        raw = await voicebot.get_catalog()

        # Normalize raw into: {"providers": [...], "local": {...}}
        normalized = _normalize_catalog_payload(raw)

        safe = sanitize_voicebot_catalog(normalized)

    except VoicebotClientError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return success_response(safe)


from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header

MOCK_CATALOG: Dict[str, Any] = {
    "success": True,
    "message": {
        "providers": ["openai", "bolna", "local"],
        "local": {
            "stt_models": [
                {
                    "id": "stt_18cfc3f6ca77",
                    "label": "stt_18cfc3f6ca77",
                    "type": "vosk_dual",
                    "languages": ["en", "hi"],
                }
            ],
            "llm_models": [
                {
                    "id": "llm_27cfaaacb385",
                    "label": "llm_27cfaaacb385",
                    "type": "llamacpp",
                    "model_name": "qwen2.5-0.5b-instruct.Q4_K_M.gguf",
                },
                {
                    "id": "llm_e965f5a3c77d",
                    "label": "llm_e965f5a3c77d",
                    "type": "llamacpp",
                    "model_name": "qwen2.5-0.5b-instruct.Q4_K_M.gguf",
                },
            ],
            "tts_models": [
                {
                    "id": "tts_f51de1f34a32",
                    "label": "tts_f51de1f34a32",
                    "type": "piper",
                    "voices": ["en", "hi"],
                },
                {
                    "id": "tts_9382350e2317",
                    "label": "tts_9382350e2317",
                    "type": "indic_parler",
                    "model": "ai4bharat/indic-parler-tts",
                    "device": "cpu",
                },
            ],
            "stacks": [
                {
                    "stack_id": "voicefin_meta_v1",
                    "label": "voicefin_meta_v1",
                    "stt_id": "stt_18cfc3f6ca77",
                    "llm_id": "llm_27cfaaacb385",
                    "tts_id": "tts_f51de1f34a32",
                    "stt": {"type": "vosk_dual", "languages": ["en", "hi"]},
                    "llm": {
                        "type": "llamacpp",
                        "model_name": "qwen2.5-0.5b-instruct.Q4_K_M.gguf",
                    },
                    "tts": {"type": "piper", "voices": ["en", "hi"], "device": None, "model": None},
                },
                {
                    "stack_id": "local_indicparler",
                    "label": "local_indicparler",
                    "stt_id": "stt_18cfc3f6ca77",
                    "llm_id": "llm_e965f5a3c77d",
                    "tts_id": "tts_9382350e2317",
                    "stt": {"type": "vosk_dual", "languages": ["en", "hi"]},
                    "llm": {
                        "type": "llamacpp",
                        "model_name": "qwen2.5-0.5b-instruct.Q4_K_M.gguf",
                    },
                    "tts": {
                        "type": "indic_parler",
                        "voices": None,
                        "device": "cpu",
                        "model": "ai4bharat/indic-parler-tts",
                    },
                },
            ],
        },
    },
    "data": None,
    "errors": None,
    "meta": {
        "timestamp": "2026-02-16T06:23:58.836447Z",
        "request_id": "unknown",
        "version": "2.0",
    },
}


@router.get("/model-catalog-mock")
def model_catalog(x_request_id: Optional[str] = Header(default=None, alias="X-Request-ID")) -> JSONResponse:
    payload = deepcopy(MOCK_CATALOG)
    payload["meta"]["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload["meta"]["request_id"] = x_request_id or "unknown"
    return JSONResponse(content=payload)


class CreateStackPayload(BaseModel):
    stt_id: str = Field(..., min_length=1, max_length=200)
    tts_id: str = Field(..., min_length=1, max_length=200)
    llm_id: Optional[str] = Field(default=None, min_length=1, max_length=200)
    stack_id: Optional[str] = Field(default=None, min_length=1, max_length=120)
    label: Optional[str] = Field(default=None, max_length=160)

@router.get("/stacks", dependencies=[Depends(require_permission("voicebot.view"))])
async def list_local_stacks(user=Depends(get_current_user)):
    try:
        vc = VoicebotClient.from_settings()
        stacks = await vc.list_stacks()
        return success_response({"stacks": stacks})
    except VoicebotClientError as e:
        raise HTTPException(status_code=502, detail=str(e))

@router.post("/stacks", dependencies=[Depends(require_permission("voicebot.manage"))])
async def create_local_stack(payload: CreateStackPayload, user=Depends(get_current_user)):
    try:
        vc = VoicebotClient.from_settings()
        url = f"{vc.base_url}/v1/stacks"
        async with httpx.AsyncClient(timeout=vc.timeout_s) as client:
            r = await client.post(
                url,
                headers={**vc._headers(), "Content-Type": "application/json"},
                json=payload.model_dump(),
            )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"voicebot create stack failed: {r.status_code}: {r.text[:600]}")
        return success_response(r.json())
    except VoicebotClientError as e:
        raise HTTPException(status_code=502, detail=str(e))