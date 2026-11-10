import base64
import json

import pytest

from app.services import sarvam


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeAsyncClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, **kwargs):
        self.kwargs["captured"] = {"url": url, **kwargs}
        if url.endswith("/speech-to-text"):
            return FakeResponse({"transcript": "medicine unavailable", "language_code": "kn-IN"})
        if url.endswith("/text-to-speech"):
            return FakeResponse({"audios": [base64.b64encode(b"wav-bytes").decode("ascii")]})
        return FakeResponse({"choices": [{"message": {"content": '{"category":"Medicine Unavailable","priority":"high","is_emergency":false,"summary_english":"Medicine stock is unavailable."}'}}]})


@pytest.fixture()
def mock_sarvam(monkeypatch):
    captures = []

    class CapturingClient(FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captures.append(self)

    monkeypatch.setattr(sarvam.httpx, "AsyncClient", CapturingClient)
    monkeypatch.setenv("SARVAM_API_KEY", "test-sarvam-key")
    return captures


@pytest.mark.asyncio
async def test_transcription_calls_documented_saaras_endpoint_and_autodetect(mock_sarvam):
    result = await sarvam.transcribe_audio(b"webm-audio", "clip.webm", "audio/webm")
    assert result == {"transcript": "medicine unavailable", "language": "kn"}
    sent = mock_sarvam[-1].kwargs["captured"]
    assert sent["url"] == "https://api.sarvam.ai/speech-to-text"
    assert sent["data"] == {"model": "saaras:v4", "language_code": "unknown"}
    assert sent["files"]["file"][2] == "audio/webm"
    assert sent["headers"]["api-subscription-key"] == "test-sarvam-key"


@pytest.mark.asyncio
async def test_speech_generation_uses_documented_kannada_voice_and_wav(mock_sarvam):
    audio = await sarvam.synthesize_speech("complaint number 1", "kn")
    assert audio == b"wav-bytes"
    sent = mock_sarvam[-1].kwargs["captured"]
    assert sent["url"] == "https://api.sarvam.ai/text-to-speech"
    assert sent["json"]["language_code"] == "kn-IN"
    assert sent["json"]["output_audio_codec"] == "wav"
    assert sent["json"]["model"] == "bulbul:v4-flash"
    assert sent["json"]["speaker"] == "chaitra_kn_narration"


@pytest.mark.asyncio
async def test_llm_classification_response_is_parsed(mock_sarvam):
    result = await sarvam.classify_with_llm("medicine unavailable")
    assert result["category"] == "Medicine Unavailable"
    sent = mock_sarvam[-1].kwargs["captured"]
    assert sent["url"] == "https://api.sarvam.ai/v2/chat/completions"
    assert sent["json"]["model"] == "sarvam-105b"


@pytest.mark.asyncio
async def test_missing_key_has_clear_fallback(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    with pytest.raises(sarvam.SarvamUnavailable, match="browser speech"):
        await sarvam.transcribe_audio(b"audio", "clip.ogg", "audio/ogg")


@pytest.mark.asyncio
async def test_tts_logs_status_and_body_without_api_key(monkeypatch, caplog):
    class ErrorClient(FakeAsyncClient):
        async def post(self, url, **kwargs):
            return FakeResponse({"message": "invalid speaker", "echo": "test-sarvam-key"}, status_code=422)

    monkeypatch.setattr(sarvam.httpx, "AsyncClient", ErrorClient)
    monkeypatch.setenv("SARVAM_API_KEY", "test-sarvam-key")
    with pytest.raises(sarvam.SarvamUnavailable, match="HTTP 422: invalid speaker"):
        await sarvam.synthesize_speech("test", "kn")
    assert "status=422" in caplog.text
    assert "invalid speaker" in caplog.text
    assert "test-sarvam-key" not in caplog.text
    assert "[REDACTED]" in caplog.text
