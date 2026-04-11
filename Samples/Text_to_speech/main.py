"""
Call Center Analyzer — Azure AI Foundry Pipeline
-------------------------------------------------
Transcribes a phone call (WAV/MP3), then runs an agentic analysis
to extract: summary, product hierarchy (L1/L2/L3), customer/agent
sentiment, tonality, and service — and exports everything to CSV.

Usage:
    python main.py --audio call.wav
    python main.py --audio call.mp3 --output results.csv --language en-US
"""

import argparse
import sys
from pathlib import Path

from transcriber import transcribe_audio
from analyzer import analyze_call
from exporter import export_to_csv


def main():
    parser = argparse.ArgumentParser(
        description="Call Center Analyzer — Azure AI Foundry Pipeline"
    )
    parser.add_argument(
        "--audio",
        required=True,
        help="Path to the audio file (WAV or MP3)",
    )
    parser.add_argument(
        "--output",
        default="call_analysis_results.csv",
        help="Path for the output CSV file (default: call_analysis_results.csv)",
    )
    parser.add_argument(
        "--language",
        default="en-US",
        help="BCP-47 language code for transcription (default: en-US)",
    )
    parser.add_argument(
        "--max-speakers",
        type=int,
        default=2,
        dest="max_speakers",
        help="Max number of speakers expected (default: 2 — customer + agent)",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"[ERROR] Audio file not found: {audio_path}")
        sys.exit(1)

    suffix = audio_path.suffix.lower()
    if suffix not in {".wav", ".mp3"}:
        print(f"[ERROR] Unsupported format '{suffix}'. Only .wav and .mp3 are supported.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  CALL CENTER ANALYZER — Azure AI Foundry")
    print(f"{'='*60}")
    print(f"  Audio file : {audio_path}")
    print(f"  Language   : {args.language}")
    print(f"  Output CSV : {args.output}")
    print(f"{'='*60}\n")

    # ── Step 1: Transcription ──────────────────────────────────────
    print("[1/3] Transcribing audio with speaker diarization...")
    transcript = transcribe_audio(
        audio_path=audio_path,
        language=args.language,
        max_speakers=args.max_speakers,
    )
    print(f"       Transcription complete ({len(transcript['full_text'])} chars)\n")

    # ── Step 2: Agentic Analysis ───────────────────────────────────
    print("[2/3] Running agentic analysis (Azure AI Foundry)...")
    analysis = analyze_call(
        audio_file=str(audio_path),
        transcript=transcript,
    )
    print("       Analysis complete\n")

    # ── Step 3: Export ─────────────────────────────────────────────
    print("[3/3] Exporting results to CSV...")
    output_path = export_to_csv(
        audio_file=str(audio_path),
        transcript=transcript,
        analysis=analysis,
        output_path=args.output,
    )
    print(f"      Results saved → {output_path}\n")

    # ── Summary printout ───────────────────────────────────────────
    print("─" * 60)
    print("  RESULTS SUMMARY")
    print("─" * 60)
    for key, value in analysis.items():
        print(f"  {key:<30} {value}")
    print("─" * 60)
    print()


if __name__ == "__main__":
    main()
