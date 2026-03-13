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
    Proxy a frontend WebSocket connection to the remote Voicebot service WebSocket.
    
    Acts as a transparent bidirectional proxy between the connected frontend WebSocket and the configured Voicebot service WebSocket, forwarding both binary and text messages in both directions. Query parameters from the incoming connection are preserved and appended to the upstream URL. If VOICEBOT_REMOTE_API_KEY is configured, an X-API-Key header is included when connecting upstream. On connection failure, the frontend WebSocket is closed if possible.
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
                """
                Forward incoming messages from the accepted frontend WebSocket to the upstream WebSocket until the client disconnects.
                
                Reads messages from the frontend, forwards binary payloads as bytes and textual payloads as text to the upstream connection, stops on client disconnect, and logs unexpected errors.
                """
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
                """
                Relays messages received from the upstream WebSocket to the frontend WebSocket.
                
                Binary payloads are forwarded as bytes and other payloads are forwarded as text. Logs an error if forwarding fails.
                """
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