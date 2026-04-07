"""
exporter.py
-----------
Exports a single call's analysis to a CSV file.
If the CSV already exists it appends a new row (idempotent column order).
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path


# ── Column order for the output CSV ─────────────────────────────────────────
CSV_COLUMNS = [
    "processed_at",
    "audio_file",
    "duration_seconds",
    "language",
    # Transcript
    "transcript_char_count",
    "transcript_turn_count",
    # Analysis outputs
    "summary",
    "product_L1",
    "product_L2",
    "product_L3",
    "customer_sentiment",
    "customer_sentiment_score",
    "customer_sentiment_reasoning",
    "agent_sentiment",
    "agent_sentiment_score",
    "agent_sentiment_reasoning",
    "tonality",
    "tonality_descriptors",
    "service",
    "action_taken",
    "resolution",
]


def export_to_csv(
    audio_file: str,
    transcript: dict,
    analysis: dict,
    output_path: str = "call_analysis_results.csv",
    language: str = "en-US",
) -> str:
    """
    Write (or append) the call analysis to a CSV file.

    Parameters
    ----------
    audio_file   : path to the source audio file
    transcript   : dict from transcriber.transcribe_audio()
    analysis     : dict from analyzer.analyze_call()
    output_path  : destination CSV path
    language     : transcription language tag

    Returns
    -------
    Resolved absolute path of the CSV file.
    """
    output_path = Path(output_path)
    file_exists = output_path.exists()

    row = {
        "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audio_file": os.path.basename(audio_file),
        "duration_seconds": round(transcript.get("duration_ms", 0) / 1000, 1),
        "language": language,
        "transcript_char_count": len(transcript.get("full_text", "")),
        "transcript_turn_count": len(transcript.get("turns", [])),
        **{k: analysis.get(k, "") for k in CSV_COLUMNS if k in analysis},
    }

    with open(output_path, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=CSV_COLUMNS,
            extrasaction="ignore",
            quoting=csv.QUOTE_ALL,
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return str(output_path.resolve())
