from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class PlivoStartInfo:
    call_uuid: Optional[str]
    stream_id: Optional[str]
    custom_parameters: Dict[str, Any]


def parse_plivo_message(msg: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    et = (msg.get("event") or "").lower()
    return et, msg


def parse_plivo_start(msg: Dict[str, Any]) -> PlivoStartInfo:
    start = msg.get("start") or {}
    return PlivoStartInfo(
        call_uuid=start.get("callUuid") or start.get("call_uuid"),
        stream_id=start.get("streamId") or start.get("stream_id"),
        custom_parameters=start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_plivo_media(msg: Dict[str, Any]) -> bytes:
    media = msg.get("media") or {}
    payload = media.get("payload") or ""
    if not payload:
        return b""
    return base64.b64decode(payload)


def build_plivo_outgoing_audio(audio_bytes: bytes, content_type: str = "audio/x-mulaw", sample_rate: int = 8000) -> str:
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {
        "event": "playAudio",
        "media": {
            "contentType": content_type,
            "sampleRate": sample_rate,
            "payload": payload,
        },
    }
    import json
    return json.dumps(out)
