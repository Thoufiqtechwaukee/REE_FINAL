"""
Shared low-level Qwen chat-completions client. Confirmed live against the
real RunPod endpoint during planning: standard OpenAI-compatible
/v1/chat/completions, response shape choices[0].message.content. Every agent
calls through this module rather than building its own HTTP request, so
retry/timeout/JSON-extraction behavior is consistent everywhere.

Design principle (plan §"Qwen never emits a number"): callers must define a
strict JSON schema and treat any unparseable/unreachable response as
"UNKNOWN / validation unavailable", never crash the pipeline and never
silently fabricate a verdict (spec §45 abstention rules, §52 failure
isolation).
"""
import json
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120.0
_MAX_RETRIES = 2


class QwenUnavailableError(Exception):
    pass


def _extract_json(raw: str) -> dict | list | None:
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    first_bracket = raw.find("[")
    last_bracket = raw.rfind("]")
    candidates = []
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(raw[first_brace : last_brace + 1])
    if first_bracket >= 0 and last_bracket > first_bracket:
        candidates.append(raw[first_bracket : last_bracket + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


async def call_chat(system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
    """Returns the raw text content, or "" if the endpoint is unreachable
    after retries. Callers decide what "no response" means for their own
    abstention rule -- this function never raises for a normal failure."""
    settings = get_settings()
    if not settings.runpod_endpoint_url:
        return ""

    headers = {"Authorization": f"Bearer {settings.runpod_api_key}"} if settings.runpod_api_key else {}
    payload = {
        "model": settings.runpod_chat_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await client.post(settings.chat_completions_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    message = choices[0].get("message", {})
                    content = message.get("content")
                    if content:
                        return content
                if "response" in data:  # Ollama /generate shape fallback
                    return data.get("response") or ""
                return ""
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("Qwen call attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)

    logger.error("Qwen endpoint unreachable after %d attempts: %s", _MAX_RETRIES, last_error)
    return ""


async def call_chat_json(system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 2048) -> dict | list | None:
    """Same as call_chat but parses the response as JSON (tolerating a model
    that wraps JSON in prose via brace/bracket extraction). Returns None on
    any failure -- unreachable endpoint, empty response, or unparseable JSON
    are all indistinguishable to the caller by design: all three mean
    "treat this as UNKNOWN / not validated", never a crash."""
    raw = await call_chat(system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens)
    return _extract_json(raw)


async def health_check() -> bool:
    result = await call_chat("Return strict JSON only.", 'Reply with exactly: {"ok": true}', max_tokens=20)
    return bool(result)
