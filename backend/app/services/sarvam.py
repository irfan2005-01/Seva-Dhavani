"""Small HTTP adapter for Sarvam's documented Model APIs.

Speech-to-text uses POST /speech-to-text with Saaras v4. REST accepts WebM and
OGG recordings directly, so the browser upload is passed through unchanged.
Text-to-speech uses POST /text-to-speech with Bulbul v4 Flash's documented Kannada
persona and WAV output.
Chat classification uses POST /v2/chat/completions with sarvam-105b.
"""

import base64
import binascii
import json
import logging
import os
import re

import httpx

API_ROOT = "https://api.sarvam.ai"
STT_MODEL = "saaras:v4"
# Bulbul v3 has a documented Kannada-capable short-name speaker (shubh).
TTS_MODEL = "bulbul:v4-flash"
CHAT_MODEL = "sarvam-105b"
logger = logging.getLogger(__name__)


class SarvamUnavailable(RuntimeError):
    """Missing key or unavailable Sarvam API."""


def _api_key() -> str:
    key = os.getenv("SARVAM_API_KEY", "").strip()
    if not key or key == "your_sarvam_api_key_here":
        raise SarvamUnavailable("SARVAM_API_KEY is not configured. Use browser speech recognition and speech synthesis instead.")
    return key


def _headers(key: str) -> dict[str, str]:
    return {"api-subscription-key": key}


async def transcribe_audio(data: bytes, filename: str, content_type: str) -> dict[str, str | None]:
    key = _api_key()
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{API_ROOT}/speech-to-text",
                headers=_headers(key),
                data={"model": STT_MODEL, "language_code": "unknown"},
                files={"file": (filename, data, content_type or "application/octet-stream")},
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SarvamUnavailable("Sarvam transcription failed. Try again or use browser speech recognition.") from exc
    transcript = result.get("transcript")
    if not transcript:
        raise SarvamUnavailable("Sarvam returned an empty transcript. Please try again or type your complaint.")
    language = result.get("language_code")
    language_map = {"kn-IN": "kn", "en-IN": "en", "hi-IN": "hi"}
    return {"transcript": transcript, "language": language_map.get(language, "kn")}


async def synthesize_speech(text: str, language: str) -> bytes:
    key = _api_key()
    language_map = {"kn": "kn-IN", "en": "en-IN", "hi": "hi-IN"}
    speaker_map = {
        "kn": "chaitra_kn_narration",
        "en": "ishita_en_customer",
        "hi": "ritu_hi_customer",
    }
    response = None
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{API_ROOT}/text-to-speech",
                headers={**_headers(key), "Content-Type": "application/json"},
                json={
                    "text": text[:2500],
                    "model": TTS_MODEL,
                    "speaker": speaker_map[language],
                    "language_code": language_map[language],
                    "output_audio_codec": "wav",
                },
            )
            if not 200 <= response.status_code < 300:
                safe_body = response.text[:2000].replace(key, "[REDACTED]")
                logger.error("Sarvam TTS failed: status=%s body=%s", response.status_code, safe_body)
                try:
                    body_json = response.json()
                    if isinstance(body_json, dict):
                        reason = body_json.get("message") or body_json.get("detail") or body_json.get("error") or safe_body
                    else:
                        reason = safe_body
                except ValueError:
                    reason = safe_body or "Sarvam returned an empty error body"
                reason = str(reason).replace(key, "[REDACTED]")
                raise SarvamUnavailable(f"Sarvam TTS returned HTTP {response.status_code}: {reason}")
            result = response.json()
        audio_list = result.get("audios") or []
        if not audio_list:
            logger.error("Sarvam TTS failed: status=%s body=%s", response.status_code, response.text[:2000].replace(key, "[REDACTED]"))
            raise SarvamUnavailable("Sarvam TTS returned no audio in the 'audios' field")
        return base64.b64decode(audio_list[0])
    except SarvamUnavailable:
        raise
    except httpx.HTTPError as exc:
        logger.error("Sarvam TTS transport failed: %s", type(exc).__name__)
        raise SarvamUnavailable("Sarvam TTS could not be reached. Use your browser's speech synthesis instead.") from exc
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        if response is not None:
            logger.error(
                "Sarvam TTS returned an invalid response: status=%s body=%s",
                response.status_code,
                response.text[:2000].replace(key, "[REDACTED]"),
            )
        logger.error("Sarvam TTS response parsing failed: %s", type(exc).__name__)
        raise SarvamUnavailable("Sarvam TTS request failed. Use your browser's speech synthesis instead.") from exc


async def classify_with_llm(text: str) -> dict | None:
    """Return structured model output, or None when the optional LLM is offline."""
    try:
        key = _api_key()
    except SarvamUnavailable:
        return None
    system = (
        "Classify this hospital service complaint. Respond only as JSON with keys "
        "category, priority, is_emergency, summary_english. category must be one of: "
        "Doctor/Staff Unavailable, Medicine Unavailable, Cleanliness & Hygiene, "
        "Drinking Water & Sanitation, Beds & Facilities, Infrastructure Maintenance, Other. "
        "priority must be low, medium, or high. is_emergency must be boolean. "
        "summary_english must be a concise English summary under 240 characters. "
        "Only flag an immediate safety emergency, not a routine service failure."
    )
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                f"{API_ROOT}/v2/chat/completions",
                headers={**_headers(key), "Content-Type": "application/json"},
                json={
                    "model": CHAT_MODEL,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": text[:5000]}],
                    "temperature": 0,
                    "max_tokens": 300,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(content).strip(), flags=re.IGNORECASE)
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None
