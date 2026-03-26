from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class TwilioStartInfo:
    call_sid: Optional[str]
    stream_sid: Optional[str]
    custom_parameters: Dict[str, Any]


def parse_twilio_message(msg: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Returns (event_type, payload)."""
    et = (msg.get("event") or "").lower()
    return et, msg


def parse_twilio_start(msg: Dict[str, Any]) -> TwilioStartInfo:
    start = msg.get("start") or {}
    return TwilioStartInfo(
        call_sid=start.get("callSid") or start.get("call_sid"),
        stream_sid=start.get("streamSid") or start.get("stream_sid"),
        custom_parameters=start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_twilio_media(msg: Dict[str, Any]) -> bytes:
    media = msg.get("media") or {}
    payload = media.get("payload") or ""
    if not payload:
        return b""
    return base64.b64decode(payload)


def build_twilio_outgoing_media(stream_sid: str, audio_bytes: bytes) -> str:
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
    import json
    return json.dumps(out)
