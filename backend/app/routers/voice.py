"""Optional voice endpoints backed by Sarvam, with browser fallbacks."""

import base64
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..services.sarvam import SarvamUnavailable, synthesize_speech, transcribe_audio

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2500)
    language: Literal["kn", "en", "hi"]


class SpeakResponse(BaseModel):
    audio_base64: str
    content_type: str = "audio/wav"


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Audio upload is empty")
    try:
        result = await transcribe_audio(data, file.filename or "recording.webm", file.content_type or "audio/webm")
    except SarvamUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


@router.post("/speak", response_model=SpeakResponse)
async def speak(payload: SpeakRequest):
    try:
        audio = await synthesize_speech(payload.text, payload.language)
    except SarvamUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "sarvam_tts_failed", "reason": str(exc)},
        ) from exc
    return SpeakResponse(audio_base64=base64.b64encode(audio).decode("ascii"))
