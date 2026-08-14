"""The model seam: descriptor phrases in, one short rhyming poem out.

Same proven pattern as debugging-saga's model seam: Gemini primary with a
reliable fallback, key from Secrets Manager, structured JSON output. There
is no deterministic fallback poem; if every model fails the caller gets an
honest error, because this app never presents non-AI output as the machine's
voice.
"""

import json
import os
import urllib.request
from typing import Optional

# Verified live on this key 2026-08-14: both returned 200 on generateContent.
MODEL_ID = os.environ.get("MODEL_ID", "gemini-flash-latest")
MODEL_FALLBACKS = [m.strip() for m in
                   os.environ.get("MODEL_FALLBACKS", "gemini-3.5-flash-lite").split(",")
                   if m.strip()]
GEMINI_SECRET_NAME = os.environ.get("GEMINI_SECRET_NAME", "infra-narrator/gemini")
_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_PRIMARY_TIMEOUT_S = int(os.environ.get("GEMINI_TIMEOUT_S", "18"))
_FALLBACK_TIMEOUT_S = int(os.environ.get("GEMINI_FALLBACK_TIMEOUT_S", "8"))

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"poem": {"type": "string"}},
    "required": ["poem"],
}

_PROMPT = """\
Current state of your body:

MOOD: {mood}

ACTIVE PROCESSES:

- traffic: {traffic_behavior}
- capacity: {scaling_behavior}
- stability: {error_condition}
- change: {deployment_activity}
- internal_flow: {queue_condition}

Instructions:
Do not list or explain these conditions.
Transform them into imagery.

Map them metaphorically:
traffic -> movement, crowds, tides, wind, flow
capacity -> expanding chambers, opening gates, stretching limbs, growing lungs
instability -> wounds, fractures, broken rhythm, sparks
change -> transformation, shedding skin, rearranging structure
internal_flow -> pressure, weight, backlog, rising water
recovery -> cooling metal, settling dust, steady heartbeat
idle -> empty halls, sleeping machinery, dim light

Write a rhyming poem describing how existence feels right now.
Do not mention computers or monitoring.
Do not narrate events, experience them.
Speak in first person as the machine.
Be 4-8 lines. Always rhyme. Be calm and minimal.
Return only the poem. Nothing else.
"""


def _api_key() -> Optional[str]:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        import boto3
        raw = boto3.client("secretsmanager").get_secret_value(
            SecretId=GEMINI_SECRET_NAME)["SecretString"]
        return json.loads(raw).get("api_key")
    except Exception:  # noqa: BLE001 - no secret / no access -> caller errors honestly
        return None


def _call_gemini(prompt: str, key: str, model_id: str, timeout: int) -> dict:
    url = f"{_API_BASE}/{model_id}:generateContent?key={key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            # Creative output wants heat; the facts are pinned upstream.
            "temperature": 0.9,
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    return json.loads(payload["candidates"][0]["content"]["parts"][0]["text"])


class PoemError(Exception):
    """Every model attempt failed; the caller should say so honestly."""


def generate_poem(mood: str, descriptors: dict) -> dict:
    """Turn descriptors into a poem. Returns {poem, model}.

    Raises PoemError if no model produced output - never fakes a poem.
    """
    key = _api_key()
    if not key:
        raise PoemError("no Gemini key available")

    prompt = _PROMPT.format(mood=mood, **{
        k: descriptors[k] for k in
        ("traffic_behavior", "scaling_behavior", "error_condition",
         "deployment_activity", "queue_condition")})

    last_err: Exception | str = "no models configured"
    for idx, model_id in enumerate([MODEL_ID, *MODEL_FALLBACKS]):
        timeout = _PRIMARY_TIMEOUT_S if idx == 0 else _FALLBACK_TIMEOUT_S
        try:
            raw = _call_gemini(prompt, key, model_id, timeout)
        except Exception as exc:  # noqa: BLE001 - try the next model
            last_err = exc
            continue
        poem = (raw.get("poem") or "").strip()
        if poem:
            return {"poem": poem, "model": model_id}
        last_err = "model returned an empty poem"
    reason = type(last_err).__name__ if isinstance(last_err, Exception) else str(last_err)
    raise PoemError(f"all models failed ({reason})")
