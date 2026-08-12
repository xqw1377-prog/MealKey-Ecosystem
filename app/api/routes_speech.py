from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.speech_service import text_to_speech, transcribe_audio_backend

router = APIRouter()


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="audio file is empty")
    result = transcribe_audio_backend(data, file.filename or "audio.wav", file.content_type or "")
    await file.close()
    if not result.text:
        raise HTTPException(status_code=502, detail="; ".join(result.warnings) or "speech transcription failed")
    return {
        "text": result.text,
        "provider": result.provider,
        "model": result.model,
        "warnings": result.warnings,
    }


@router.post("/tts")
def tts(payload: TTSRequest):
    """文字转语音——让 AI 店长的回答可以被"听到"。

    返回 base64 编码的音频，前端直接播放。
    """
    result = text_to_speech(payload.text, voice=payload.voice)
    if not result.ok:
        return {
            "ok": False,
            "warnings": result.warnings,
        }
    return {
        "ok": True,
        "audio": result.audio_base64,
        "format": result.audio_format,
        "provider": result.provider,
        "model": result.model,
    }
