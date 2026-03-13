from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


DEFAULT_SCHEMA = {
    "qualified": "boolean: whether the lead is qualified",
    "qualification_score": "0-100 integer score",
    "lead": {
        "name": "string or null",
        "age": "int or null",
        "gender": "string or null",
        "city": "string or null",
        "loan_type": "string or null",
        "monthly_income": "number or null",
        "notes": "string or null",
    },
    "summary": "short summary",
    "next_action": "string",
}


def _build_prompt(transcript: str, schema: Dict[str, Any]) -> list[dict[str, str]]:
    """
    Builds chat messages that instruct a model to extract post-call analytics as strict JSON following the provided schema.
    
    Parameters:
    	transcript (str): The call transcript to analyze.
    	schema (dict[str, Any]): The JSON schema describing the expected analytics fields and structure.
    
    Returns:
    	list[dict[str, str]]: A list of chat messages (each with 'role' and 'content') suitable for a chat-based API request.
    """
    system = (
        "You are a strict JSON generator for post-call analytics.\n"
        "Return ONLY valid minified JSON and nothing else.\n"
        "If a field is unknown, set it to null.\n"
        "Do not hallucinate.\n"
    )
    user = (
        "Extract post-call analytics from the transcript.\n\n"
        f"SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def extract_post_call_analytics(
    transcript: str,
    schema: Optional[Dict[str, Any]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract structured post-call analytics from a call transcript using an OpenAI-compatible chat endpoint.
    
    Parameters:
        transcript (str): The full call transcript to analyze.
        schema (Optional[Dict[str, Any]]): Schema guiding the JSON extraction; if omitted, a default schema is used.
        provider (Optional[str]): Analytics provider to use; supported values include "openai", "openai_compat", and "disabled" (when "disabled" the function returns an empty dict).
        model (Optional[str]): Model identifier to request; if omitted, the configured analytics or default chat model is used.
    
    Returns:
        Dict[str, Any]: Parsed analytics as a dictionary. Returns an empty dict when the provider is "disabled", when no API key is available, on HTTP errors, or when the response cannot be parsed into the expected JSON structure.
    """
    s = get_settings()
    provider = (provider or s.ANALYTICS_PROVIDER or "openai").lower()
    if provider == "disabled":
        return {}

    schema = schema or DEFAULT_SCHEMA
    messages = _build_prompt(transcript, schema)
    model = model or s.ANALYTICS_MODEL or s.OPENAI_CHAT_MODEL

    # Use openai-compatible Chat Completions via HTTP (works for OpenAI and local gateways)
    base_url = (s.ANALYTICS_BASE_URL or s.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    api_key = s.ANALYTICS_API_KEY or s.OPENAI_API_KEY
    if not api_key:
        logger.warning("analytics_no_api_key")
        return {}

    url = base_url + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            logger.error("analytics_failed", status=r.status_code, body=r.text)
            return {}
        data = r.json()

    try:
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        # Some gateways return already-parsed JSON in tool outputs, etc.
        try:
            return data
        except Exception:
            return {}
