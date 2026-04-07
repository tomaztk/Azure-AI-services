"""
transcriber.py
--------------
Transcribes a WAV or MP3 call recording using azure-ai-transcription
(Azure AI Speech fast-transcription API) with speaker diarization.

Speaker labels are mapped to roles:
  - Speaker 1 → AGENT  (typically the first voice in a call center call)
  - Speaker 2 → CUSTOMER

Env vars required:
  AZURE_SPEECH_ENDPOINT  — e.g. https://<region>.api.cognitive.microsoft.com/
  AZURE_SPEECH_API_KEY   — or use DefaultAzureCredential (RBAC)
"""

import os
import tempfile
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import (
    TranscriptionContent,
    TranscriptionOptions,
)


def _get_client() -> TranscriptionClient:
    """Build a TranscriptionClient from env-vars or managed identity."""
    endpoint = os.environ["AZURE_SPEECH_ENDPOINT"]
    api_key = os.environ.get("AZURE_SPEECH_API_KEY")

    if api_key:
        credential = AzureKeyCredential(api_key)
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()

    return TranscriptionClient(endpoint=endpoint, credential=credential)


def _convert_mp3_to_wav(mp3_path: Path) -> Path:
    """
    Convert MP3 → WAV (PCM 16-bit mono) using pydub / ffmpeg.
    Returns path to a temporary WAV file.
    """
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise ImportError(
            "pydub is required for MP3 support. "
            "Install with: pip install pydub  (ffmpeg must also be on PATH)"
        ) from exc

    audio = AudioSegment.from_mp3(str(mp3_path))
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    audio.export(tmp.name, format="wav")
    return Path(tmp.name)


def transcribe_audio(
    audio_path: Path,
    language: str = "en-US",
    max_speakers: int = 2,
) -> dict:
    """
    Transcribe an audio file and return a structured dict:
    {
        "full_text":  str,          # combined transcript
        "turns": [                  # per-phrase turn list
            {
                "speaker":    str,  # "AGENT" | "CUSTOMER" | "UNKNOWN"
                "speaker_id": int,  # raw speaker index (0-based)
                "text":       str,
                "start_ms":   int,
                "end_ms":     int,
            },
            ...
        ],
        "agent_text":    str,       # agent-only transcript
        "customer_text": str,       # customer-only transcript
        "duration_ms":   int,
    }
    """
    client = _get_client()

    wav_path = audio_path
    tmp_wav = None

    if audio_path.suffix.lower() == ".mp3":
        print("      Converting MP3 → WAV …")
        tmp_wav = _convert_mp3_to_wav(audio_path)
        wav_path = tmp_wav

    try:
        with open(wav_path, "rb") as audio_file:
            options = TranscriptionOptions(
                locales=[language],
            )
            request_content = TranscriptionContent(
                definition=options,
                audio=audio_file,
            )
            result = client.transcribe(request_content)
    finally:
        if tmp_wav and tmp_wav.exists():
            tmp_wav.unlink()

    # ── Parse phrases and assign speaker roles ─────────────────────
    # Speaker index → role mapping.
    # In call-center recordings the convention is:
    #   Speaker 0 → AGENT (opens the call)
    #   Speaker 1 → CUSTOMER
    # If diarization is unavailable, all turns fall back to UNKNOWN.
    speaker_role_map: dict[int, str] = {}

    turns = []
    for phrase in (result.phrases or []):
        # speaker attribute may be None when diarization is not enabled
        raw_speaker = getattr(phrase, "speaker", None)

        if raw_speaker is None:
            role = "UNKNOWN"
            speaker_id = -1
        else:
            speaker_id = int(raw_speaker)
            if speaker_id not in speaker_role_map:
                # Assign AGENT to the first speaker seen, CUSTOMER to the second
                role = "AGENT" if len(speaker_role_map) == 0 else "CUSTOMER"
                speaker_role_map[speaker_id] = role
            role = speaker_role_map[speaker_id]

        start_ms = getattr(phrase, "offset_milliseconds", 0) or 0
        duration_ms = getattr(phrase, "duration_milliseconds", 0) or 0

        turns.append(
            {
                "speaker": role,
                "speaker_id": speaker_id,
                "text": phrase.text.strip(),
                "start_ms": start_ms,
                "end_ms": start_ms + duration_ms,
            }
        )

    # ── Build combined and role-specific transcripts ───────────────
    full_lines = [f"[{t['speaker']}] {t['text']}" for t in turns]
    full_text = "\n".join(full_lines)

    agent_lines = [t["text"] for t in turns if t["speaker"] == "AGENT"]
    customer_lines = [t["text"] for t in turns if t["speaker"] == "CUSTOMER"]

    agent_text = " ".join(agent_lines)
    customer_text = " ".join(customer_lines)

    # Fallback: if diarization didn't work use combined phrases
    if not full_text and result.combined_phrases:
        full_text = result.combined_phrases[0].text

    duration_ms = getattr(result, "duration_milliseconds", 0) or 0

    return {
        "full_text": full_text,
        "turns": turns,
        "agent_text": agent_text,
        "customer_text": customer_text,
        "duration_ms": duration_ms,
    }
