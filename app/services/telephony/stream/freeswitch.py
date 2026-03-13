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
    """
    Parse an incoming text WebSocket frame and classify it into a FreeSWITCH event type.
    
    If `raw` is valid JSON this returns a tuple with the determined event type and the parsed JSON object. Event type will be one of: 'start', 'media', 'stop', 'connected', or 'message'. If `raw` is not valid JSON the event type is 'metadata' and the payload is `{"text": raw}`.
    
    Returns:
        (event_type, payload_dict): `event_type` is the classification string; `payload_dict` is the parsed JSON object for JSON input or `{"text": raw}` for non-JSON input.
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
    """
    Extract FreeSwitch start information from a message dictionary.
    
    Parameters:
        msg (Dict[str, Any]): Parsed JSON message that contains either a top-level start object or start-related fields.
    
    Returns:
        FreeSwitchStartInfo: Dataclass with:
            - call_id: the call identifier extracted from one of `call_id`, `callId`, `uuid`, or `callSid`.
            - stream_id: the stream identifier extracted from one of `stream_id`, `streamId`, or `streamSid`.
            - metadata: a dictionary of metadata extracted from `metadata`, `customParameters`, or `custom_parameters` (empty dict if absent).
    """
    start = msg.get("start") or msg
    return FreeSwitchStartInfo(
        call_id=start.get("call_id") or start.get("callId") or start.get("uuid") or start.get("callSid"),
        stream_id=start.get("stream_id") or start.get("streamId") or start.get("streamSid"),
        metadata=start.get("metadata") or start.get("customParameters") or start.get("custom_parameters") or {},
    )


def parse_freeswitch_media(msg: Dict[str, Any]) -> bytes:
    """
    Extracts audio data from a FreeSWITCH-style JSON message.
    
    Parameters:
        msg (Dict[str, Any]): JSON-like message that may include a base64-encoded audio payload under
            "media" -> "payload", "audio", or "payload".
    
    Returns:
        bytes: Decoded audio bytes from the first matching base64 payload, or empty bytes if no payload is found.
    """
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
    """
    Build an outgoing FreeSWITCH media frame.
    
    When as_json is True, returns a JSON string containing a base64-encoded payload in the shape {"event": "media", "media": {"payload": "<base64>"}}. When as_json is False, returns the raw audio bytes unchanged.
    
    Parameters:
        as_json (bool): Whether to wrap the audio bytes in a JSON media frame with a base64 payload.
    
    Returns:
        str | bytes: JSON string with base64 payload if as_json is True, otherwise the original audio bytes.
    """
    if not as_json:
        return audio_bytes
    payload = base64.b64encode(audio_bytes).decode("ascii")
    out = {"event": "media", "media": {"payload": payload}}
    import json

    return json.dumps(out)
