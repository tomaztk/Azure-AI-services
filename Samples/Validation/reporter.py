"""
reporter.py
-----------
Formats ValidationReport objects for terminal output and CSV export.
"""

from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from validator import ValidationReport


# ── Terminal colours ──────────────────────────────────────────────────────────
class C:
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    GREEN  = "\033[92m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"


def _status_icon(status: str) -> str:
    return {
        "PASS": f"{C.GREEN}● PASS{C.RESET}",
        "WARN": f"{C.YELLOW}▲ WARN{C.RESET}",
        "FAIL": f"{C.RED}✖ FAIL{C.RESET}",
    }.get(status, status)


def print_report(report: "ValidationReport", compact: bool = False) -> None:
    status_str = _status_icon(report.overall_status)
    conf = f"{report.confidence * 100:.0f}%"

    print(f"      Status   : {status_str}   Confidence: {conf}")

    if compact:
        # One-line summary per layer
        e = len(report.schema_issues)
        w = len(report.rules_issues)
        k = len(report.kb_issues)
        ev = len(report.eval_issues)
        ag = len(report.agent_findings)
        cf = len(report.corrected_fields)
        print(
            f"      Layers   : "
            f"Rules {C.RED if e else C.GREEN}{e}err{C.RESET}/"
            f"{C.YELLOW if w else C.GREEN}{w}warn{C.RESET}  "
            f"KB {C.RED if k else C.GREEN}{k}iss{C.RESET}  "
            f"Eval {C.RED if ev else C.GREEN}{ev}iss{C.RESET}  "
            f"Agent {C.RED if ag else C.GREEN}{ag}findings{C.RESET}  "
            f"Corrections: {cf}"
        )
        print()
        return

    # ── Full report ───────────────────────────────────────────────────────────
    print(f"\n  {'─' * 58}")
    print(f"  VALIDATION REPORT  ·  {report.record_id}")
    print(f"  {'─' * 58}")
    print(f"  Status     : {status_str}")
    print(f"  Confidence : {conf}")
    print(f"  Validated  : {report.validated_at}")

    if report.schema_issues:
        print(f"\n  {C.RED}[Layer 1/2] SCHEMA & RULE ERRORS{C.RESET}")
        for r in report.schema_issues:
            print(f"    ✖ [{r.field}] {r.message}")

    if report.rules_issues:
        print(f"\n  {C.YELLOW}[Layer 1/2] RULE WARNINGS{C.RESET}")
        for r in report.rules_issues:
            print(f"    ▲ [{r.field}] {r.message}")

    if report.kb_issues:
        print(f"\n  {C.RED}[Layer 3] KNOWLEDGE-BASE ISSUES{C.RESET}")
        for iss in report.kb_issues:
            print(f"    ✖ {iss}")

    if report.eval_scores:
        print(f"\n  {C.CYAN}[Layer 4] AI EVALUATION SCORES{C.RESET}")
        for metric, score in report.eval_scores.items():
            bar = "█" * int((score or 0)) + "░" * (5 - int(score or 0))
            print(f"    {metric:<15} {bar}  {score}/5")
        if report.eval_issues:
            print(f"  {C.YELLOW}  Issues:{C.RESET}")
            for iss in report.eval_issues:
                print(f"    ▲ {iss}")

    if report.agent_findings:
        print(f"\n  {C.YELLOW}[Layer 5] AGENT FINDINGS{C.RESET}")
        for f in report.agent_findings:
            print(f"    ▲ {f}")

    if report.corrected_fields:
        print(f"\n  {C.CYAN}[Agent] SUGGESTED CORRECTIONS{C.RESET}")
        for field_name, correction in report.corrected_fields.items():
            print(
                f"    ► {field_name}: "
                f"'{correction.get('suggested_value')}' "
                f"(confidence {correction.get('confidence', 0):.0%}) — "
                f"{correction.get('reason', '')}"
            )

    if report.overall_status == "PASS":
        print(f"\n  {C.GREEN}All validation layers passed ✓{C.RESET}")

    print(f"  {'─' * 58}\n")


# ── CSV export ─────────────────────────────────────────────────────────────────
_CSV_COLUMNS = [
    "validated_at",
    "record_id",
    "overall_status",
    "confidence",
    # Layer counts
    "schema_error_count",
    "rule_warning_count",
    "kb_issue_count",
    "eval_issue_count",
    "agent_finding_count",
    "correction_count",
    # AI eval scores
    "groundedness_score",
    "relevance_score",
    "coherence_score",
    # Detail strings
    "schema_errors",
    "kb_issues",
    "agent_findings",
    "corrected_fields",
]


def export_report_csv(
    reports: list["ValidationReport"],
    output_path: str = "validation_results.csv",
) -> str:
    output_path = Path(output_path)
    file_exists = output_path.exists()

    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore", quoting=csv.QUOTE_ALL)
        if not file_exists:
            writer.writeheader()

        for r in reports:
            scores = r.eval_scores or {}
            writer.writerow({
                "validated_at": r.validated_at,
                "record_id": r.record_id,
                "overall_status": r.overall_status,
                "confidence": r.confidence,
                "schema_error_count": len(r.schema_issues),
                "rule_warning_count": len(r.rules_issues),
                "kb_issue_count": len(r.kb_issues),
                "eval_issue_count": len(r.eval_issues),
                "agent_finding_count": len(r.agent_findings),
                "correction_count": len(r.corrected_fields),
                "groundedness_score": scores.get("groundedness", ""),
                "relevance_score": scores.get("relevance", ""),
                "coherence_score": scores.get("coherence", ""),
                "schema_errors": " | ".join(e.message for e in r.schema_issues),
                "kb_issues": " | ".join(r.kb_issues),
                "agent_findings": " | ".join(r.agent_findings),
                "corrected_fields": json.dumps(r.corrected_fields),
            })

    return str(output_path.resolve())
