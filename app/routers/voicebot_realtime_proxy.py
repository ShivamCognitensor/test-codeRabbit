from __future__ import annotations

import asyncio
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
import websockets

from app.core.auth import get_current_user, require_permission
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/ui", tags=["UI-Realtime"])


@router.websocket("/voicebot/ws")
async def voicebot_ws_proxy(
    ws: WebSocket,
):
    """
    Frontend WS -> LMS -> VoicebotService WS
    LMS is a transparent proxy (bytes + text both directions).

    Frontend connects:
      ws(s)://<lms-host>/api/v1/ui/voicebot/ws?stack_id=...&session_id=...&agent_name=...
    """
    s = get_settings()

    await ws.accept()

    # Optional: if you want auth on WS, enforce it:
    # (FastAPI auth deps do not work directly on WS the same way, so do header-based validation if needed)

    # Build remote URL
    base = (s.VOICEBOT_REMOTE_BASE_URL or "").rstrip("/")
    remote = f"{base}/v1/voicebot/ws"

    qp = dict(ws.query_params)
    remote_qs = urllib.parse.urlencode(qp)
    remote_url = f"{remote}?{remote_qs}" if remote_qs else remote

    headers = []
    if s.VOICEBOT_REMOTE_API_KEY:
        headers.append(("X-API-Key", s.VOICEBOT_REMOTE_API_KEY))

    try:
        async with websockets.connect(remote_url, extra_headers=headers, ping_interval=20) as upstream:

            async def client_to_upstream():
                try:
                    while True:
                        msg = await ws.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])
                        elif msg.get("text"):
                            await upstream.send(msg["text"])
                except WebSocketDisconnect:
                    return
                except Exception as e:
                    logger.error("WS proxy client_to_upstream error: %s", str(e))

            async def upstream_to_client():
                try:
                    async for umsg in upstream:
                        if isinstance(umsg, (bytes, bytearray)):
                            await ws.send_bytes(bytes(umsg))
                        else:
                            await ws.send_text(str(umsg))
                except Exception as e:
                    logger.error("WS proxy upstream_to_client error: %s", str(e))

            await asyncio.gather(client_to_upstream(), upstream_to_client())

    except Exception as e:
        logger.error("WS proxy failed: %s", str(e))
        try:
            await ws.close()
        except Exception:
            pass