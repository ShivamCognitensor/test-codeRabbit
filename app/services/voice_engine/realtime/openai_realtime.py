from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncIterator, Dict, Optional

import websockets

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.voice_engine.realtime.base import RealtimeBridge, RealtimeConfig

logger = get_logger(__name__)


class OpenAIRealtimeBridge(RealtimeBridge):
    """OpenAI Realtime WebSocket bridge (audio-to-audio)."""

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.s = get_settings()
        self.model = model or self.s.OPENAI_REALTIME_MODEL
        self.base_url = base_url or self.s.OPENAI_REALTIME_URL
        self.api_key = api_key or self.s.OPENAI_API_KEY
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._closed = False
        self._audio_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._recv_task: Optional[asyncio.Task] = None
        self._transcript: list[dict[str, Any]] = []

    @property
    def transcript(self) -> list[dict[str, Any]]:
        return self._transcript

    async def connect(self, config: RealtimeConfig) -> None:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        if not self.model:
            raise RuntimeError("OPENAI_REALTIME_MODEL not set")

        url = (self.base_url or "wss://api.openai.com/v1/realtime").rstrip("/")
        # model is required as query param for realtime websocket
        ws_url = f"{url}?model={self.model}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            # Realtime beta header; kept for compatibility
            "OpenAI-Beta": "realtime=v1",
        }

        self._ws = await websockets.connect(ws_url, extra_headers=headers, max_queue=32, ping_interval=20, ping_timeout=20)
        self._closed = False

        # Configure session: use g711_ulaw for PSTN (Twilio/Plivo) and let the model transcribe as guidance.
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": config.instructions,
                "input_audio_format": config.input_audio_format,
                "output_audio_format": config.output_audio_format,
                # voice is model-dependent; if not supported it will be ignored or error.
                "voice": config.voice,
                "turn_detection": {
                    "type": "server_vad",
                    # Ensure the model generates a response automatically when VAD detects the user stopped speaking.
                    "create_response": True,
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 650,
                },
                # optional transcription for analytics
                "input_audio_transcription": {
                    "model": self.s.OPENAI_TRANSCRIBE_MODEL or "gpt-4o-mini-transcribe",
                    "language": config.language,
                },
                "interrupt_response": True,
                # Non-standard but ignored by OpenAI; used by our local gateway.
                "metadata": config.metadata or {},
            },
        }
        # clean None values
        session_update["session"] = {k: v for k, v in session_update["session"].items() if v is not None}

        await self._ws.send(json.dumps(session_update))

        # Start receiver loop
        self._recv_task = asyncio.create_task(self._recv_loop())

        # Proactively request a greeting turn if configured.
        if self.s.OPENAI_REALTIME_START_WITH_GREETING:
            await self._ws.send(json.dumps({"type": "response.create"}))

    async def send_audio(self, audio_bytes: bytes) -> None:
        if self._closed or not self._ws:
            return
        if not audio_bytes:
            return
        msg = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(audio_bytes).decode("ascii"),
        }
        await self._ws.send(json.dumps(msg))

    async def recv_audio(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._audio_q.get()
            if chunk is None:  # type: ignore[comparison-overlap]
                break
            yield chunk

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        # unblock recv_audio
        await self._audio_q.put(None)  # type: ignore[arg-type]

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    evt = json.loads(raw)
                except Exception:
                    continue

                etype = evt.get("type")
                if etype == "error":
                    logger.error("openai_realtime_error", error=evt.get("error"))
                    continue

                # Audio deltas from the model
                if etype == "response.output_audio.delta":
                    delta_b64 = evt.get("delta") or ""
                    if delta_b64:
                        try:
                            audio = base64.b64decode(delta_b64)
                            await self._audio_q.put(audio)
                        except Exception:
                            pass
                    continue

                # transcripts (optional, best-effort)
                if etype == "conversation.item.input_audio_transcription.completed":
                    # some builds use this event name
                    transcript = ((evt.get("transcript") or {}) if isinstance(evt.get("transcript"), dict) else None)
                    text = None
                    if transcript:
                        text = transcript.get("text")
                    if not text:
                        text = evt.get("text") or evt.get("transcript")
                    if text:
                        self._transcript.append({"role": "user", "text": str(text)})
                    continue

                if etype == "response.output_audio_transcript.done":
                    text = evt.get("transcript")
                    if text:
                        self._transcript.append({"role": "assistant", "text": str(text)})
                    continue

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("openai_realtime_recv_failed", error=str(e))
        finally:
            await self.close()
