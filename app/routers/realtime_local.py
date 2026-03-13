"""Local OpenAI-Realtime-compatible WebSocket.

Purpose: allow the existing telephony gateway to stream audio to an *open-source*
voice pipeline (STT->LLM->TTS or native A2A models) using the same protocol the
OpenAI Realtime bridge expects.

Endpoint:
  WS /v1/realtime?model=...   (model query is ignored but accepted)

Auth:
  If LOCAL_A2A_API_KEY is set, requires: Authorization: Bearer <key>
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.audio.codecs import alaw8k_to_pcm16_16k, ulaw8k_to_pcm16_16k
from app.services.voice_engine.realtime.local_gateway import LocalRealtimeSession

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["local-realtime"])


def _auth_ok(ws: WebSocket) -> bool:
    """
    Check whether the incoming WebSocket connection is authorized according to LOCAL_A2A_API_KEY.
    
    If LOCAL_A2A_API_KEY is unset (empty/falsey), authorization is not required and the function returns True. Otherwise the function expects an Authorization header with the Bearer scheme and returns True only if the provided token exactly matches LOCAL_A2A_API_KEY.
    
    Parameters:
        ws (WebSocket): The incoming WebSocket connection whose headers will be inspected.
    
    Returns:
        bool: `true` if the connection is authorized, `false` otherwise.
    """
    s = get_settings()
    if not s.LOCAL_A2A_API_KEY:
        return True
    auth = ws.headers.get("authorization") or ws.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return False
    token = auth.split(" ", 1)[1].strip()
    return token == s.LOCAL_A2A_API_KEY


@router.websocket("/realtime")
async def local_realtime_ws(ws: WebSocket):
    """
    Handle a WebSocket realtime session that streams client audio into a local voice pipeline.
    
    Accepts and authenticates the incoming WebSocket connection (closes with code 4401 if unauthorized), starts a background LocalRealtimeSession loop, and processes incoming JSON messages to update session state, append audio buffers, or trigger responses. Supported message types:
    - "session.update": update session state from the provided dict and reply with {"type": "session.updated"}.
    - "input_audio_buffer.append": accept a base64-encoded audio payload, decode it, convert to PCM16 16k when the session input_audio_format indicates g711 ulaw/mulaw or g711 alaw/alaw, and append PCM16 16k audio to the session.
    - "response.create": force the session to produce a response.
    
    Parameters:
        ws (WebSocket): The FastAPI WebSocket connection for the client.
    """
    if not _auth_ok(ws):
        await ws.close(code=4401)
        return
    await ws.accept()

    sess = LocalRealtimeSession()

    async def send_json(obj: Dict[str, Any]) -> None:
        """
        Send a JSON-serializable object to the connected WebSocket client as a text message, preserving non-ASCII characters.
        
        Parameters:
            obj (Dict[str, Any]): The mapping to serialize to JSON and send.
        """
        await ws.send_text(json.dumps(obj, ensure_ascii=False))

    # Start background loop for turn handling
    bg_task = asyncio.create_task(sess.run_loop(send_json))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = msg.get("type")
            if mtype == "session.update":
                session = msg.get("session") or {}
                if isinstance(session, dict):
                    sess.update_from_session(session)
                await send_json({"type": "session.updated"})
                continue

            if mtype == "input_audio_buffer.append":
                b64 = msg.get("audio") or ""
                if not b64:
                    continue
                try:
                    audio = base64.b64decode(b64)
                except Exception:
                    continue

                fmt = (sess.cfg.input_audio_format or "g711_ulaw").lower().strip()
                if fmt in ("g711_ulaw", "ulaw", "mulaw"):
                    pcm = ulaw8k_to_pcm16_16k(audio)
                elif fmt in ("g711_alaw", "alaw"):
                    pcm = alaw8k_to_pcm16_16k(audio)
                else:
                    # assume PCM16 16k
                    pcm = None
                if pcm is None:
                    sess.append_audio_pcm16_16k(audio)
                else:
                    sess.append_audio_pcm16_16k(pcm.pcm16)
                continue

            if mtype == "response.create":
                sess.force_response()
                continue

    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("local_realtime_ws_error")
    finally:
        bg_task.cancel()
        try:
            await ws.close()
        except Exception:
            pass
