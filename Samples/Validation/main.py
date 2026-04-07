"""
Validation of Information — Azure AI Foundry Demo
==================================================
Enterprise-grade information validation pipeline that combines:

  Layer 1 · Schema & Completeness   — are all required fields present and typed?
  Layer 2 · Business Rules          — do values comply with domain rules?
  Layer 3 · Knowledge-Base Lookup   — are facts consistent with the KB?
  Layer 4 · Groundedness (AI eval)  — is the AI-generated text grounded in source?
  Layer 5 · Contradiction Detection — are fields internally consistent?

Typical use-case: validate JSON records produced by an upstream AI extraction
pipeline (e.g. the Call Center Analyzer) before they reach a BI dashboard or CRM.

Usage:
    # Validate a JSON record interactively
    python main.py --input sample_record.json

    # Validate a whole batch (JSONL — one record per line)
    python main.py --input records.jsonl --batch

    # Run the built-in demo with synthetic data
    python main.py --demo
"""

import argparse
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from validator import validate_record
from reporter import print_report, export_report_csv


def _banner():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  INFORMATION VALIDATION DEMO  ·  Azure AI Foundry           ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def run_demo():
    """Run validation against a set of synthetic call-centre records."""
    from demo_data import DEMO_RECORDS
    _banner()
    print(f"  Running demo with {len(DEMO_RECORDS)} synthetic records …\n")
    results = []
    for i, record in enumerate(DEMO_RECORDS, 1):
        print(f"  ─── Record {i}/{len(DEMO_RECORDS)}: {record.get('audio_file', 'unknown')} ───")
        report = validate_record(record)
        print_report(report, compact=True)
        results.append(report)

    csv_path = export_report_csv(results, output_path="validation_results.csv")
    print(f"\n  ✓ Full validation report exported → {csv_path}\n")


def run_single(input_path: Path):
    _banner()
    with open(input_path) as f:
        record = json.load(f)
    print(f"  Validating: {input_path.name}\n")
    report = validate_record(record)
    print_report(report, compact=False)
    csv_path = export_report_csv([report], output_path="validation_results.csv")
    print(f"\n  ✓ Report exported → {csv_path}\n")


def run_batch(input_path: Path):
    _banner()
    records = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"  Batch mode: {len(records)} records from {input_path.name}\n")
    results = []
    for i, record in enumerate(records, 1):
        print(f"  ─── Record {i}/{len(records)} ───")
        report = validate_record(record)
        print_report(report, compact=True)
        results.append(report)

    csv_path = export_report_csv(results, output_path="validation_results.csv")
    print(f"\n  ✓ Batch report exported → {csv_path}\n")


def main():
    parser = argparse.ArgumentParser(description="Information Validation Demo — Azure AI Foundry")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="Run built-in demo with synthetic data")
    group.add_argument("--input", type=Path, help="Path to a JSON or JSONL file")
    parser.add_argument("--batch", action="store_true", help="Treat --input as JSONL batch file")
    args = parser.parse_args()

    if args.demo:
        run_demo()
    elif args.batch:
        run_batch(args.input)
    else:
        run_single(args.input)


if __name__ == "__main__":
    main()
