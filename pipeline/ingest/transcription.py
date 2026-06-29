from __future__ import annotations
from pathlib import Path


def transcribe_audio(audio_path: Path, api_key: str, model: str = "whisper-large-v3") -> str:
    from groq import Groq
    client = Groq(api_key=api_key)
    with audio_path.open("rb") as f:
        transcription = client.audio.transcriptions.create(
            file=(audio_path.name, f),
            model=model,
            response_format="text",
        )
    return transcription
