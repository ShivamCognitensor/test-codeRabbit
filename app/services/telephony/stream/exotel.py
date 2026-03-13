from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ExotelStartInfo:
    call_sid: Optional[str]
    stream_sid: Optional[str]
    custom_parameters: Dict[str, Any]


def parse_exotel_message(msg: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    et = (msg.get("event") or msg.get("type") or "").lower()
    return et, msg


def parse_exotel_start(msg: Dict[str, Any]) -> ExotelStartInfo:
    start = msg.get("start") or msg.get("data") or msg
    return ExotelStartInfo(
        call_sid=start.get("callSid") or start.get("call_sid") or start.get("CallSid"),
        stream_sid=start.get("streamSid") or start.get("stream_sid") or start.get("StreamSid"),
        custom_parameters=start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_exotel_media(msg: Dict[str, Any]) -> bytes:
    media = msg.get("media") or msg.get("data") or {}
    payload = media.get("payload") or media.get("audio") or ""
    if not payload:
        return b""
    return base64.b64decode(payload)


def build_exotel_outgoing_audio(audio_bytes: bytes, encoding: str = "audio/x-mulaw", sample_rate: int = 8000) -> str:
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {"event": "playAudio", "media": {"encoding": encoding, "sampleRate": sample_rate, "payload": payload}}
    import json
    return json.dumps(out)
