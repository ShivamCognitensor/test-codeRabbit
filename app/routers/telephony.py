from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_permission
from app.core.config import get_settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.models.agent_profile import AgentProfile
from app.models.campaign import CampaignContact
from app.services.telephony.registry import build_registry
from app.services.telephony.types import OutboundCallRequest
from app.services.telephony.stream.twilio import (
    parse_twilio_message,
    parse_twilio_start,
    parse_twilio_media,
    build_twilio_outgoing_media,
)
from app.services.telephony.stream.plivo import (
    parse_plivo_message,
    parse_plivo_start,
    parse_plivo_media,
    build_plivo_outgoing_audio,
)
from app.services.telephony.stream.exotel import (
    parse_exotel_message,
    parse_exotel_start,
    parse_exotel_media,
    build_exotel_outgoing_audio,
)
from app.services.telephony.stream.freeswitch import (
    parse_freeswitch_text_message,
    parse_freeswitch_start,
    parse_freeswitch_media,
    build_freeswitch_outgoing_media,
)
from app.services.voice_engine.prompting import build_instructions
from app.services.voice_engine.realtime.openai_realtime import OpenAIRealtimeBridge
from app.services.voice_engine.realtime.base import RealtimeConfig
from app.services.voice_engine.post_call import finalize_call
from shared.responses import success_response

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/telephony", tags=["Telephony"])
registry = build_registry()


@router.get("/providers", dependencies=[Depends(require_permission("voicebot.view"))])
async def list_providers(user=Depends(get_current_user)):
    """
    List registered telephony providers and their enabled status.
    
    Returns:
        A success response containing a list of objects each with:
        - `name`: provider identifier string
        - `enabled`: `true` if the provider is enabled, `false` otherwise
    """
    items = []
    for name, p in registry.list().items():
        items.append({"name": name, "enabled": bool(getattr(p, "is_enabled", True))})
    return success_response(items)


class OutboundCallPayload(Dict[str, Any]):
    """Just for docs."""


@router.post("/outbound", dependencies=[Depends(require_permission("voicebot.manage"))])
async def start_outbound_call(payload: Dict[str, Any], db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """
    Initiates an outbound call with the selected telephony provider and returns provider call metadata.
    
    Parameters:
        payload (Dict[str, Any]): Request payload containing at minimum:
            - "provider": provider key (string)
            - "to_phone" or "to": destination phone number (string)
            Optional keys:
            - "from_phone" or "from": caller phone number (string)
            - "agent_profile_id": UUID string of an agent profile
            - "campaign_contact_id": UUID string of a CampaignContact to associate with this call
            - "campaign_id": UUID string of a campaign
            - "variables": dict of variables to attach to the outbound request
    
    Returns:
        Dict[str, Any]: A success response containing:
            - "provider": provider key used
            - "provider_call_id": provider-assigned call identifier
            - "provider_stream_id": provider-assigned stream identifier (if any)
            - "to": destination phone number
            - "from": caller phone number or null
    
    Raises:
        HTTPException: status 400 if required fields are missing or the provider is unknown.
    
    Side effects:
        If "campaign_contact_id" is provided and the corresponding CampaignContact exists,
        stores minimal telephony provider metadata into that contact's `responses` and commits it to the database.
    """
    provider = str(payload.get("provider") or "").strip().lower()
    to_phone = str(payload.get("to_phone") or payload.get("to") or "").strip()
    if not provider or not to_phone:
        raise HTTPException(status_code=400, detail="provider and to_phone are required")

    from_phone = str(payload.get("from_phone") or payload.get("from") or "").strip() or None
    agent_profile_id = payload.get("agent_profile_id")
    campaign_contact_id = payload.get("campaign_contact_id")
    campaign_id = payload.get("campaign_id")

    prov = registry.get(provider)
    if not prov:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    req = OutboundCallRequest(
        provider=provider,
        to_phone=to_phone,
        from_phone=from_phone,
        agent_profile_id=UUID(agent_profile_id) if agent_profile_id else None,
        campaign_contact_id=UUID(campaign_contact_id) if campaign_contact_id else None,
        campaign_id=UUID(campaign_id) if campaign_id else None,
        variables=payload.get("variables") if isinstance(payload.get("variables"), dict) else None,
    )
    info = await prov.start_outbound_call(req)

    # persist provider call id if tied to a contact
    if req.campaign_contact_id:
        contact = await db.get(CampaignContact, req.campaign_contact_id)
        if contact:
            # store minimal provider metadata in responses
            contact.responses = (contact.responses or {}) | {
                "telephony": {
                    "provider": info.provider,
                    "provider_call_id": info.provider_call_id,
                    "provider_stream_id": info.provider_stream_id,
                }
            }
            await db.commit()

    return success_response(
        {
            "provider": info.provider,
            "provider_call_id": info.provider_call_id,
            "provider_stream_id": info.provider_stream_id,
            "to": info.to_phone,
            "from": info.from_phone,
        }
    )


# ---------------------------------------------------------------------
# Twilio hooks
# ---------------------------------------------------------------------
@router.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request):
    """
    Handle incoming Twilio voice webhook requests by delegating processing to the configured Twilio provider.
    
    Raises:
        HTTPException: If the Twilio provider is not configured.
    
    Returns:
        The response produced by the Twilio provider's webhook handler, suitable for returning to Twilio.
    """
    prov = registry.get("twilio")
    if not prov:
        raise HTTPException(500, "Twilio provider missing")
    return await prov.answer_hook(request)


@router.post("/twilio/status")
async def twilio_status(request: Request):
    # Optional: verify signature (X-Twilio-Signature). Keeping minimal for now.
    """
    Handle Twilio status webhook requests.
    
    Parameters:
        request (Request): Incoming HTTP request containing Twilio status form data.
    
    Returns:
        dict: A JSON-serializable response with {"ok": True} acknowledging receipt.
    """
    payload = await request.form()
    logger.info("twilio_status", payload=dict(payload))
    return {"ok": True}


@router.websocket("/twilio/ws")
async def twilio_ws(ws: WebSocket, db: AsyncSession = Depends(get_db)):
    """
    Handle a Twilio WebSocket session, bridging audio between Twilio and the realtime assistant and managing call lifecycle.
    
    Listens for Twilio "start", "media", and "stop" messages: on "start" it initializes a realtime bridge using optional agent profile and campaign contact context (building instructions, pipeline settings, voice/language, and audio formats); on "media" it forwards incoming audio to the bridge; while connected it streams bridge-produced audio back to Twilio in the expected outbound format. On disconnect or stop it closes the bridge, cancels the sender task, and attempts to finalize the call (saving transcript and provider metadata) when a campaign contact is associated.
    """
    await ws.accept()
    s = get_settings()

    stream_sid: Optional[str] = None
    call_sid: Optional[str] = None
    agent_profile_id: Optional[UUID] = None
    campaign_contact_id: Optional[UUID] = None

    bridge: Optional[OpenAIRealtimeBridge] = None
    sender_task: Optional[asyncio.Task] = None

    try:
        # receive loop
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            et, _ = parse_twilio_message(msg)

            if et == "start":
                info = parse_twilio_start(msg)
                stream_sid = info.stream_sid
                call_sid = info.call_sid
                cp = info.custom_parameters or {}

                # Prefer custom params; fall back to querystring
                ap = cp.get("agent_profile_id") or ws.query_params.get("agent_profile_id")
                cc = cp.get("campaign_contact_id") or ws.query_params.get("campaign_contact_id")
                if ap:
                    agent_profile_id = UUID(str(ap))
                if cc:
                    campaign_contact_id = UUID(str(cc))

                agent = await db.get(AgentProfile, agent_profile_id) if agent_profile_id else None
                variables: Dict[str, Any] = {}
                if campaign_contact_id:
                    contact = await db.get(CampaignContact, campaign_contact_id)
                    if contact:
                        variables.update({"lead": contact.lead_data or {}, "contact": contact.to_dict() if hasattr(contact, "to_dict") else {}})

                instructions = build_instructions(
                    system_prompt=(agent.system_prompt if agent else None),
                    prompt_template=(agent.prompt_template if agent else None),
                    variables=variables,
                ) or "You are a helpful voice assistant."

                # pipeline selection
                pipe = (agent.pipeline_config if agent and isinstance(agent.pipeline_config, dict) else {}) or {}
                realtime_provider = (pipe.get("realtime_provider") or "openai").lower()
                realtime_model = pipe.get("realtime_model") or None

                input_fmt = pipe.get("input_audio_format") or "g711_ulaw"
                output_fmt = pipe.get("output_audio_format") or "g711_ulaw"

                if realtime_provider == "local" and s.LOCAL_A2A_WS_URL:
                    bridge = OpenAIRealtimeBridge(model=realtime_model or s.LOCAL_A2A_MODEL, base_url=s.LOCAL_A2A_WS_URL, api_key=s.LOCAL_A2A_API_KEY)
                else:
                    bridge = OpenAIRealtimeBridge(model=realtime_model or s.OPENAI_REALTIME_MODEL, base_url=s.OPENAI_REALTIME_URL, api_key=s.OPENAI_API_KEY)

                voice_id = None
                language = None
                if agent and isinstance(agent.voice_config, dict):
                    voice_id = agent.voice_config.get("voice_id")
                if agent:
                    language = agent.language

                await bridge.connect(
                    RealtimeConfig(
                        instructions=instructions,
                        input_audio_format=input_fmt,
                        output_audio_format=output_fmt,
                        voice=voice_id,
                        language=language,
                        metadata={"call_sid": call_sid, "stream_sid": stream_sid, "provider": "twilio", "stt_provider": (pipe.get("stt_provider") or None), "tts_provider": (pipe.get("tts_provider") or None), "llm_provider": (pipe.get("llm_provider") or None), "voicebot_stack_id": (pipe.get("voicebot_stack_id") or None)},
                    )
                )

                async def _sender():
                    """
                    Forward audio chunks received from the realtime bridge to the connected Twilio WebSocket as Twilio-compatible outgoing media frames using the current stream SID.
                    
                    The coroutine consumes bridge.recv_audio() until it completes and sends each chunk over the WebSocket.
                    """
                    assert bridge is not None
                    assert stream_sid is not None
                    async for chunk in bridge.recv_audio():
                        # Twilio expects outbound audio in same codec as the stream.
                        await ws.send_text(build_twilio_outgoing_media(stream_sid, chunk))

                sender_task = asyncio.create_task(_sender())
                continue

            if et == "media":
                if not bridge:
                    continue
                audio_ulaw = parse_twilio_media(msg)
                await bridge.send_audio(audio_ulaw)
                continue

            if et == "stop":
                break

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("twilio_ws_error")
    finally:
        if sender_task:
            sender_task.cancel()
        if bridge:
            await bridge.close()
            # finalize call if tied to a campaign contact
            try:
                await finalize_call(db, campaign_contact_id, agent_profile_id, bridge.transcript, provider_meta={"provider": "twilio", "call_sid": call_sid, "stream_sid": stream_sid})
            except Exception:
                logger.exception("twilio_finalize_failed")
        await ws.close()


# ---------------------------------------------------------------------
# Plivo hooks
# ---------------------------------------------------------------------
@router.api_route("/plivo/answer", methods=["GET", "POST"])
async def plivo_answer(request: Request):
    """
    Handle Plivo's answer webhook by delegating the incoming request to the configured Plivo provider.
    
    Parameters:
        request (Request): Incoming HTTP request from Plivo.
    
    Returns:
        The HTTP response produced by the Plivo provider's answer_hook (typically an XML or HTTP response suitable for Plivo).
    
    Raises:
        HTTPException: If the Plivo provider is not configured.
    """
    prov = registry.get("plivo")
    if not prov:
        raise HTTPException(500, "Plivo provider missing")
    return await prov.answer_hook(request)


@router.post("/plivo/status")
async def plivo_status(request: Request):
    """
    Handle Plivo call status webhook by logging the raw request body.
    
    Returns:
        dict: {'ok': True} to acknowledge successful receipt.
    """
    payload = await request.body()
    logger.info("plivo_status", payload=payload.decode("utf-8", errors="ignore"))
    return {"ok": True}


@router.websocket("/plivo/ws")
async def plivo_ws(ws: WebSocket, db: AsyncSession = Depends(get_db)):
    """
    Handle a Plivo WebSocket session that bridges realtime audio between Plivo and the realtime AI engine.
    
    Accepts Plivo stream messages and:
    - On a "start" message: resolves agent and contact context, builds instructions and pipeline settings, selects realtime backend/model and audio formats, connects a realtime bridge with Plivo-specific metadata, and starts a background sender that forwards audio from the bridge to Plivo.
    - On "media" messages: forwards incoming Plivo audio frames into the realtime bridge.
    - On "stop"/"hangup"/"end" or on disconnect: cancels the sender task, closes the bridge, attempts to finalize the call (persisting transcript and provider metadata including provider name, call UUID, and stream ID), and closes the WebSocket.
    
    Errors during the session are logged; the function performs best-effort finalization when possible.
    """
    await ws.accept()
    s = get_settings()

    stream_id: Optional[str] = None
    call_uuid: Optional[str] = None
    agent_profile_id: Optional[UUID] = None
    campaign_contact_id: Optional[UUID] = None

    bridge: Optional[OpenAIRealtimeBridge] = None
    sender_task: Optional[asyncio.Task] = None

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            et, _ = parse_plivo_message(msg)

            if et == "start":
                info = parse_plivo_start(msg)
                stream_id = info.stream_id
                call_uuid = info.call_uuid
                cp = info.custom_parameters or {}

                ap = cp.get("agent_profile_id") or ws.query_params.get("agent_profile_id")
                cc = cp.get("campaign_contact_id") or ws.query_params.get("campaign_contact_id")
                if ap:
                    agent_profile_id = UUID(str(ap))
                if cc:
                    campaign_contact_id = UUID(str(cc))

                agent = await db.get(AgentProfile, agent_profile_id) if agent_profile_id else None
                variables: Dict[str, Any] = {}
                if campaign_contact_id:
                    contact = await db.get(CampaignContact, campaign_contact_id)
                    if contact:
                        variables.update({"lead": contact.lead_data or {}})

                instructions = build_instructions(
                    system_prompt=(agent.system_prompt if agent else None),
                    prompt_template=(agent.prompt_template if agent else None),
                    variables=variables,
                ) or "You are a helpful voice assistant."

                pipe = (agent.pipeline_config if agent and isinstance(agent.pipeline_config, dict) else {}) or {}
                realtime_provider = (pipe.get("realtime_provider") or "openai").lower()
                realtime_model = pipe.get("realtime_model") or None
                input_fmt = pipe.get("input_audio_format") or "g711_ulaw"
                output_fmt = pipe.get("output_audio_format") or "g711_ulaw"

                if realtime_provider == "local" and s.LOCAL_A2A_WS_URL:
                    bridge = OpenAIRealtimeBridge(model=realtime_model or s.LOCAL_A2A_MODEL, base_url=s.LOCAL_A2A_WS_URL, api_key=s.LOCAL_A2A_API_KEY)
                else:
                    bridge = OpenAIRealtimeBridge(model=realtime_model or s.OPENAI_REALTIME_MODEL, base_url=s.OPENAI_REALTIME_URL, api_key=s.OPENAI_API_KEY)

                voice_id = None
                language = None
                if agent and isinstance(agent.voice_config, dict):
                    voice_id = agent.voice_config.get("voice_id")
                if agent:
                    language = agent.language

                await bridge.connect(
                    RealtimeConfig(
                        instructions=instructions,
                        input_audio_format=input_fmt,
                        output_audio_format=output_fmt,
                        voice=voice_id,
                        language=language,
                        metadata={"call_uuid": call_uuid, "stream_id": stream_id, "provider": "plivo"},
                    )
                )

                async def _sender():
                    """
                    Continuously forward audio frames from the realtime bridge to the WebSocket as Plivo-formatted outgoing audio.
                    
                    Reads audio frames from the connected realtime bridge and sends them to the client WebSocket encoded using the Plivo outgoing audio format until the bridge closes.
                    """
                    assert bridge is not None
                    async for chunk in bridge.recv_audio():
                        await ws.send_text(build_plivo_outgoing_audio(chunk))

                sender_task = asyncio.create_task(_sender())
                continue

            if et == "media":
                if not bridge:
                    continue
                audio_ulaw = parse_plivo_media(msg)
                await bridge.send_audio(audio_ulaw)
                continue

            if et in ("stop", "hangup", "end"):
                break

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("plivo_ws_error")
    finally:
        if sender_task:
            sender_task.cancel()
        if bridge:
            await bridge.close()
            try:
                await finalize_call(db, campaign_contact_id, agent_profile_id, bridge.transcript, provider_meta={"provider": "plivo", "call_uuid": call_uuid, "stream_id": stream_id})
            except Exception:
                logger.exception("plivo_finalize_failed")
        await ws.close()


# ---------------------------------------------------------------------
# Exotel hooks (AgentStream)
# ---------------------------------------------------------------------
@router.get("/exotel/stream-url")
async def exotel_stream_url(request: Request):
    """
    Provide the WebSocket URL clients should use to connect to the Exotel AgentStream endpoint.
    
    If the TELEPHONY_PUBLIC_WS_BASE setting is defined and non-empty, it is used as the base WebSocket URL; otherwise the URL is derived from the incoming request's base URL. The returned URL targets the /api/v1/telephony/exotel/ws route.
    
    Returns:
        dict: A mapping with key `url` containing the full WebSocket endpoint URL as a string.
    """
    s = get_settings()
    ws_base = (s.TELEPHONY_PUBLIC_WS_BASE or "").strip()
    if not ws_base:
        ws_base = str(request.base_url).replace("http://", "ws://").replace("https://", "wss://").rstrip("/")
    url = ws_base + "/api/v1/telephony/exotel/ws"
    return {"url": url}


@router.post("/exotel/status")
async def exotel_status(request: Request):
    """
    Handle Exotel status webhook requests by parsing form-encoded data and logging the payload.
    
    Returns:
        dict: A dictionary with `"ok": True` indicating the request was processed.
    """
    data = await request.form()
    logger.info("exotel_status", payload=dict(data))
    return {"ok": True}


@router.websocket("/exotel/ws")
async def exotel_ws(ws: WebSocket, db: AsyncSession = Depends(get_db)):
    """
    Handle an Exotel AgentStream WebSocket session, bridging audio between Exotel and a realtime voice model.
    
    This connection processes Exotel messages (e.g., start/connected/media/stop), initializes a realtime bridge using optional agent profile and campaign contact context, forwards incoming audio to the bridge, streams bridge audio back to Exotel-formatted outgoing audio, and finalizes the call (persisting transcript and provider metadata) when the session ends.
    
    Parameters:
        ws: The active WebSocket connection for the Exotel AgentStream.
        db: Database session used to load AgentProfile and CampaignContact and to persist finalization data.
    """
    await ws.accept()
    s = get_settings()

    stream_sid: Optional[str] = None
    call_sid: Optional[str] = None
    agent_profile_id: Optional[UUID] = None
    campaign_contact_id: Optional[UUID] = None

    bridge: Optional[OpenAIRealtimeBridge] = None
    sender_task: Optional[asyncio.Task] = None

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            et, _ = parse_exotel_message(msg)

            if et in ("start", "connected", "connection"):
                info = parse_exotel_start(msg)
                stream_sid = info.stream_sid
                call_sid = info.call_sid
                cp = info.custom_parameters or {}

                ap = cp.get("agent_profile_id") or ws.query_params.get("agent_profile_id")
                cc = cp.get("campaign_contact_id") or ws.query_params.get("campaign_contact_id")
                if ap:
                    agent_profile_id = UUID(str(ap))
                if cc:
                    campaign_contact_id = UUID(str(cc))

                agent = await db.get(AgentProfile, agent_profile_id) if agent_profile_id else None
                variables: Dict[str, Any] = {}
                if campaign_contact_id:
                    contact = await db.get(CampaignContact, campaign_contact_id)
                    if contact:
                        variables.update({"lead": contact.lead_data or {}})

                instructions = build_instructions(
                    system_prompt=(agent.system_prompt if agent else None),
                    prompt_template=(agent.prompt_template if agent else None),
                    variables=variables,
                ) or "You are a helpful voice assistant."

                pipe = (agent.pipeline_config if agent and isinstance(agent.pipeline_config, dict) else {}) or {}
                realtime_provider = (pipe.get("realtime_provider") or "openai").lower()
                realtime_model = pipe.get("realtime_model") or None
                # Exotel AgentStream commonly uses PCM16 (slin16). If your AgentStream is configured
                # for mulaw/8k, override these in the agent profile.
                input_fmt = pipe.get("input_audio_format") or "pcm16"
                output_fmt = pipe.get("output_audio_format") or "pcm16"

                if realtime_provider == "local" and s.LOCAL_A2A_WS_URL:
                    bridge = OpenAIRealtimeBridge(model=realtime_model or s.LOCAL_A2A_MODEL, base_url=s.LOCAL_A2A_WS_URL, api_key=s.LOCAL_A2A_API_KEY)
                else:
                    bridge = OpenAIRealtimeBridge(model=realtime_model or s.OPENAI_REALTIME_MODEL, base_url=s.OPENAI_REALTIME_URL, api_key=s.OPENAI_API_KEY)

                voice_id = None
                language = None
                if agent and isinstance(agent.voice_config, dict):
                    voice_id = agent.voice_config.get("voice_id")
                if agent:
                    language = agent.language

                await bridge.connect(
                    RealtimeConfig(
                        instructions=instructions,
                        input_audio_format=input_fmt,
                        output_audio_format=output_fmt,
                        voice=voice_id,
                        language=language,
                        metadata={"call_sid": call_sid, "stream_sid": stream_sid, "provider": "exotel", "stt_provider": (pipe.get("stt_provider") or None), "tts_provider": (pipe.get("tts_provider") or None), "llm_provider": (pipe.get("llm_provider") or None), "voicebot_stack_id": (pipe.get("voicebot_stack_id") or None)},
                    )
                )

                async def _sender():
                    """
                    Continuously forwards audio frames from the realtime bridge to the WebSocket as Exotel playAudio messages.
                    
                    Reads audio chunks from bridge.recv_audio() and, for each chunk, sends the text message produced by build_exotel_outgoing_audio(chunk) over the WebSocket until the bridge stream ends.
                    """
                    assert bridge is not None
                    async for chunk in bridge.recv_audio():
                        # For Exotel, we default to sending playAudio with encoding matching input_fmt.
                        await ws.send_text(build_exotel_outgoing_audio(chunk))

                sender_task = asyncio.create_task(_sender())
                continue

            if et == "media":
                if not bridge:
                    continue
                audio = parse_exotel_media(msg)
                await bridge.send_audio(audio)
                continue

            if et in ("stop", "disconnected", "hangup", "end"):
                break

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("exotel_ws_error")
    finally:
        if sender_task:
            sender_task.cancel()
        if bridge:
            await bridge.close()
            try:
                await finalize_call(db, campaign_contact_id, agent_profile_id, bridge.transcript, provider_meta={"provider": "exotel", "call_sid": call_sid, "stream_sid": stream_sid})
            except Exception:
                logger.exception("exotel_finalize_failed")
        await ws.close()


@router.websocket("/freeswitch/ws")
async def freeswitch_ws(ws: WebSocket, db: AsyncSession = Depends(get_db)):
    """
    Handle a FreeSWITCH WebSocket session for bidirectional telephony audio and metadata.
    
    Accepts FreeSWITCH/mod_audio_stream and mod_twilio_stream message formats, establishes a realtime bridge to the configured speech/LLM backend, forwards incoming audio to the bridge, and streams bridge audio back to FreeSWITCH in the appropriate output format. On session end the call is finalized and the bridge transcript is persisted with provider metadata.
    """

    await ws.accept()

    s = get_settings()

    agent_profile_id: Optional[UUID] = None
    campaign_contact_id: Optional[UUID] = None
    call_id: Optional[str] = None

    bridge: Optional[OpenAIRealtimeBridge] = None
    sender_task: Optional[asyncio.Task] = None
    send_as_json: bool = True

    started = False

    async def _ensure_bridge(default_input: str, default_output: str, meta: Dict[str, Any]):
        """
        Ensure a realtime OpenAI bridge is created, connected, and streaming audio to the WebSocket with the given default formats and metadata.
        
        When not already started, reads agent_profile_id, campaign_contact_id, and call_id from query params or provided meta and sets corresponding local IDs; loads agent and contact data to build instruction variables; selects realtime provider/model and audio formats (falling back to defaults); creates and connects an OpenAIRealtimeBridge with metadata for FreeSWITCH; and starts a background sender task that forwards audio chunks from the bridge to the WebSocket. This function mutates the enclosing scope's `bridge`, `sender_task`, `started`, `agent_profile_id`, `campaign_contact_id`, and `call_id`.
        """
        nonlocal bridge, sender_task, started, agent_profile_id, campaign_contact_id, call_id
        if started:
            return

        ap = ws.query_params.get("agent_profile_id")
        cc = ws.query_params.get("campaign_contact_id")
        cid = ws.query_params.get("call_id")
        if ap and not agent_profile_id:
            try:
                meta["agent_profile_id"] = ap
            except Exception:
                pass
        if cc and not campaign_contact_id:
            try:
                meta["campaign_contact_id"] = cc
            except Exception:
                pass
        if cid and not call_id:
            meta["call_id"] = cid

        _agent_id = meta.get("agent_profile_id")
        _contact_id = meta.get("campaign_contact_id")
        _call_id = meta.get("call_id")

        if _agent_id and not agent_profile_id:
            agent_profile_id = UUID(str(_agent_id))
        if _contact_id and not campaign_contact_id:
            campaign_contact_id = UUID(str(_contact_id))
        if _call_id and not call_id:
            call_id = str(_call_id)

        agent = await db.get(AgentProfile, agent_profile_id) if agent_profile_id else None
        variables: Dict[str, Any] = {}
        if campaign_contact_id:
            contact = await db.get(CampaignContact, campaign_contact_id)
            if contact:
                variables.update({"lead": contact.lead_data or {}, "contact": contact.to_dict() if hasattr(contact, "to_dict") else {}})
        # Include any FS provided variables
        if isinstance(meta.get("variables"), dict):
            variables.update(meta.get("variables"))

        instructions = build_instructions(
            system_prompt=(agent.system_prompt if agent else None),
            prompt_template=(agent.prompt_template if agent else None),
            variables=variables,
        ) or "You are a helpful voice assistant."

        pipe = (agent.pipeline_config if agent and isinstance(agent.pipeline_config, dict) else {}) or {}
        realtime_provider = (pipe.get("realtime_provider") or "openai").lower()
        realtime_model = pipe.get("realtime_model") or None

        input_fmt = pipe.get("input_audio_format") or default_input
        output_fmt = pipe.get("output_audio_format") or default_output

        if realtime_provider == "local" and s.LOCAL_A2A_WS_URL:
            bridge = OpenAIRealtimeBridge(model=realtime_model or s.LOCAL_A2A_MODEL, base_url=s.LOCAL_A2A_WS_URL, api_key=s.LOCAL_A2A_API_KEY)
        else:
            bridge = OpenAIRealtimeBridge(model=realtime_model or s.OPENAI_REALTIME_MODEL, base_url=s.OPENAI_REALTIME_URL, api_key=s.OPENAI_API_KEY)

        voice_id = None
        language = None
        if agent and isinstance(agent.voice_config, dict):
            voice_id = agent.voice_config.get("voice_id")
        if agent:
            language = agent.language

        await bridge.connect(
            RealtimeConfig(
                instructions=instructions,
                input_audio_format=input_fmt,
                output_audio_format=output_fmt,
                voice=voice_id,
                language=language,
                metadata={"provider": "freeswitch", "call_id": call_id},
            )
        )

        async def _sender():
            """
            Continuously forward audio frames from the realtime bridge to the FreeSWITCH WebSocket in the provider's expected format.
            
            Reads audio chunks from the bridge, formats each chunk as either binary frames or text/JSON frames depending on send_as_json, and sends them over the WebSocket connection.
            """
            assert bridge is not None
            async for chunk in bridge.recv_audio():
                out = build_freeswitch_outgoing_media(chunk, as_json=send_as_json)
                if isinstance(out, bytes):
                    await ws.send_bytes(out)
                else:
                    await ws.send_text(out)

        sender_task = asyncio.create_task(_sender())
        started = True

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if "bytes" in msg and msg["bytes"] is not None:
                # raw-binary mode: treat as PCM16 frames
                send_as_json = False
                await _ensure_bridge("pcm16", "pcm16", meta={})
                if bridge:
                    await bridge.send_audio(msg["bytes"])
                continue

            if "text" not in msg or msg["text"] is None:
                continue

            raw = msg["text"]
            et, payload = parse_freeswitch_text_message(raw)

            if et in {"metadata"}:
                # metadata text frame sent by mod_audio_stream before media starts
                meta: Dict[str, Any] = {}
                try:
                    meta = json.loads(payload.get("text") or "{}")
                except Exception:
                    # best-effort parse k=v pairs
                    txt = str(payload.get("text") or "")
                    for part in txt.split(","):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            meta[k.strip()] = v.strip()
                await _ensure_bridge("pcm16", "pcm16", meta=meta)
                continue

            if et == "start":
                info = parse_freeswitch_start(payload)
                meta = dict(info.metadata or {})
                if info.call_id:
                    meta["call_id"] = info.call_id
                if info.stream_id:
                    meta["stream_id"] = info.stream_id
                # Twilio-like JSON streams are usually PCMU
                send_as_json = True
                await _ensure_bridge("g711_ulaw", "g711_ulaw", meta=meta)
                continue

            if et == "media":
                # JSON base64 audio
                send_as_json = True
                await _ensure_bridge("g711_ulaw", "g711_ulaw", meta={})
                if bridge:
                    await bridge.send_audio(parse_freeswitch_media(payload))
                continue

            if et in {"stop", "hangup", "disconnected", "end"}:
                break

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("freeswitch_ws_error")
    finally:
        if sender_task:
            sender_task.cancel()
        if bridge:
            await bridge.close()
            try:
                await finalize_call(db, campaign_contact_id, agent_profile_id, bridge.transcript, provider_meta={"provider": "freeswitch", "call_id": call_id})
            except Exception:
                logger.exception("freeswitch_finalize_failed")
        await ws.close()
