from __future__ import annotations

"""Helpers for FreeSWITCH WebSocket audio streaming.

We support two common FreeSWITCH streaming approaches:

1) **mod_twilio_stream** (open-source): sends Twilio-like JSON messages
   (event=start/media/stop with media.payload base64). In this case you can
   reuse the /telephony/twilio/ws endpoint directly.

2) **mod_audio_stream** (community/commercial):
   - community edition: L16 PCM audio to WS + optional text responses.
   - commercial edition: adds full-duplex playback and supports both
     base64 JSON and raw binary streaming.

Because deployments vary, this module provides a permissive parser that can:
 - accept Twilio-style JSON (event/media.payload)
 - accept a simple JSON shape: {"type":"audio","audio":"<b64>","codec":"pcmu"}
 - accept raw binary frames (handled at the WS endpoint level)
"""

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class FreeSwitchStartInfo:
    call_id: Optional[str]
    stream_id: Optional[str]
    metadata: Dict[str, Any]


def parse_freeswitch_text_message(raw: str) -> Tuple[str, Dict[str, Any]]:
    """Parse an incoming **text** frame.

    Returns (event_type, payload_dict).

    - If it's JSON, we try to map it to event=start/media/stop.
    - If it's not JSON, treat it as metadata (event="metadata").
    """
    import json

    try:
        msg = json.loads(raw)
    except Exception:
        return "metadata", {"text": raw}

    # Twilio-like
    et = (msg.get("event") or msg.get("type") or "").lower()
    if et in {"start", "media", "stop", "connected"}:
        return et, msg

    # Some servers send {"kind":"audio", "audio":"..."}
    kind = (msg.get("kind") or msg.get("type") or "").lower()
    if kind in {"audio", "media"}:
        return "media", msg

    return "message", msg


def parse_freeswitch_start(msg: Dict[str, Any]) -> FreeSwitchStartInfo:
    start = msg.get("start") or msg
    return FreeSwitchStartInfo(
        call_id=start.get("call_id") or start.get("callId") or start.get("uuid") or start.get("callSid"),
        stream_id=start.get("stream_id") or start.get("streamId") or start.get("streamSid"),
        metadata=start.get("metadata") or start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_freeswitch_media(msg: Dict[str, Any]) -> bytes:
    """Extract audio bytes from a JSON message."""
    # Twilio-like
    media = msg.get("media") or {}
    payload = media.get("payload")
    if payload:
        return base64.b64decode(payload)

    # Alternative
    payload = msg.get("audio") or msg.get("payload")
    if payload:
        return base64.b64decode(payload)

    return b""


def build_freeswitch_outgoing_media(audio_bytes: bytes, *, as_json: bool = True) -> str | bytes:
    """Build an outgoing frame.

    - If `as_json=True`, returns a JSON string with base64 payload (Twilio-like).
    - Else returns raw bytes (for raw-binary mode).
    """
    if not as_json:
        return audio_bytes
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {"event": "media", "media": {"payload": payload}}
    import json

    return json.dumps(out)
