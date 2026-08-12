from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SpeechTranscriptionResult:
    text: str
    warnings: list[str]
    provider: str
    model: str


def _env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    try:
        from app.services.settings_store import get_setting

        return (get_setting(name.lower()) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _openai_compatible_asr_config() -> tuple[str, str, str] | None:
    api_key = _env("ASR_API_KEY") or _env("QWEN_API_KEY") or _env("DASHSCOPE_API_KEY")
    base_url = _env("ASR_BASE_URL") or _env("QWEN_BASE_URL")
    model = _env("ASR_MODEL") or _env("QWEN_ASR_MODEL") or "qwen3-asr-flash"
    if not (api_key and base_url and model):
        return None
    return api_key, base_url.rstrip("/"), model


def _service_endpoint_config() -> tuple[str, str | None] | None:
    url = _env("ASR_SERVICE_URL")
    if not url:
        return None
    token = _env("ASR_SERVICE_TOKEN") or None
    return url.rstrip("/"), token


def _multipart_body(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----MealKeySpeechBoundary{os.urandom(12).hex()}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for field_name, filename, content, content_type in files:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n".encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), boundary


def _transcribe_with_service(data: bytes, filename: str, content_type: str) -> SpeechTranscriptionResult:
    config = _service_endpoint_config()
    if not config:
        return SpeechTranscriptionResult(text="", warnings=["未配置独立语音服务。"], provider="", model="")
    url, token = config
    body, boundary = _multipart_body(
        {"language": "zh"},
        [("file", filename, data, content_type or "application/octet-stream")],
    )
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "MealKey-SpeechService/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{url}/transcribe",
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return SpeechTranscriptionResult(
            text="",
            warnings=[f"独立语音服务转写失败：{exc}"],
            provider="service",
            model="external-asr",
        )
    return SpeechTranscriptionResult(
        text=(payload.get("text") or payload.get("transcript") or "").strip(),
        warnings=[] if (payload.get("text") or payload.get("transcript")) else ["独立语音服务未返回可用文本。"],
        provider="service",
        model=payload.get("model") or "external-asr",
    )


def _transcribe_with_openai_compatible_asr(data: bytes, filename: str) -> SpeechTranscriptionResult:
    config = _openai_compatible_asr_config()
    if not config:
        return SpeechTranscriptionResult(text="", warnings=["未配置 ASR 模型。"], provider="", model="")
    api_key, base_url, model = config
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(data).decode("ascii"),
                            "format": (Path(filename).suffix.lower() or ".wav").lstrip("."),
                        },
                    },
                    {
                        "type": "text",
                        "text": "请把这段音频准确转写成简体中文，保留关键数字、菜名、价格和经营术语。",
                    },
                ],
            }
        ],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 1200,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "MealKey-SpeechService/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return SpeechTranscriptionResult(
            text="",
            warnings=[f"ASR 转写失败：{exc}"],
            provider="openai-compatible-asr",
            model=model,
        )
    choice = (raw.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = (message.get("content") or "").strip()
    return SpeechTranscriptionResult(
        text=content,
        warnings=[] if content else ["ASR 模型未返回可用文本。"],
        provider="openai-compatible-asr",
        model=model,
    )


def transcribe_audio_backend(data: bytes, filename: str, content_type: str) -> SpeechTranscriptionResult:
    _ = content_type
    return _transcribe_with_openai_compatible_asr(data, filename)


def transcribe_audio_bytes(data: bytes, filename: str, content_type: str) -> tuple[str, list[str]]:
    service_result = _transcribe_with_service(data, filename, content_type)
    if service_result.text:
        return service_result.text, service_result.warnings
    if _service_endpoint_config():
        return "", service_result.warnings

    asr_result = _transcribe_with_openai_compatible_asr(data, filename)
    if asr_result.text:
        return asr_result.text, [*asr_result.warnings, "当前使用 ASR 模型回退通道，建议后续接入独立语音服务。"]
    return "", [
        *asr_result.warnings,
        "当前未接入独立语音服务，音频文件暂时只能依赖回退转写通道。",
    ]


# ═══════════════════════════════════════════════════════════
# TTS（文字转语音）— 让 AI 店长能"说话"
# ═══════════════════════════════════════════════════════════


@dataclass
class TTSResult:
    ok: bool
    audio_base64: str = ""  # base64 编码的 MP3/WAV
    audio_format: str = "mp3"
    provider: str = ""
    model: str = ""
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def _tts_config() -> tuple[str, str, str, str] | None:
    """获取 TTS 配置：(api_key, base_url, model, voice)"""
    api_key = _env("TTS_API_KEY") or _env("DASHSCOPE_API_KEY") or _env("QWEN_API_KEY")
    base_url = _env("TTS_BASE_URL") or _env("QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = _env("TTS_MODEL") or _env("QWEN_TTS_MODEL") or "qwen-tts"
    voice = _env("TTS_VOICE") or "longxiaochun"
    if not api_key:
        return None
    return api_key, base_url, model, voice


def text_to_speech(text: str, *, voice: str | None = None) -> TTSResult:
    """文字转语音——让 AI 店长的回答可以被"听到"。

    支持 OpenAI 兼容的 TTS 接口（如千问 TTS / CosyVoice）。
    返回 base64 编码的音频，前端直接 <audio> 播放。
    """
    config = _tts_config()
    if config is None:
        return TTSResult(
            ok=False,
            warnings=["TTS 服务未配置。设置 TTS_API_KEY 或 DASHSCOPE_API_KEY 后可用。"],
        )

    api_key, base_url, model, default_voice = config
    use_voice = voice or default_voice

    try:
        payload = json.dumps({
            "model": model,
            "input": text[:500],  # TTS 不需要超长文本
            "voice": use_voice,
        }).encode("utf-8")

        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/audio/speech",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            audio_data = response.read()

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        content_type = response.headers.get("Content-Type", "audio/mpeg")
        fmt = "mp3" if "mpeg" in content_type else "wav" if "wav" in content_type else "mp3"

        return TTSResult(
            ok=True,
            audio_base64=audio_b64,
            audio_format=fmt,
            provider="openai-compatible",
            model=model,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return TTSResult(ok=False, warnings=[f"TTS HTTP {exc.code}: {detail[:200]}"])
    except Exception as exc:  # noqa: BLE001
        return TTSResult(ok=False, warnings=[f"TTS failed: {type(exc).__name__}: {str(exc)[:100]}"])
