"""
rules_engine.py
---------------
Layer 2 validation: business rules checked before calling the AI agent.
These are deterministic checks that don't need LLM inference.

Each check returns a RuleResult named tuple:
    passed  — True / False
    field   — the field that was checked
    message — human-readable explanation
    severity — "error" | "warning" | "info"
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from knowledge_base import get_policies, lookup_sentiment, lookup_tonality, lookup_resolution


@dataclass
class RuleResult:
    field: str
    passed: bool
    message: str
    severity: str = "error"   # "error" | "warning" | "info"


def run_all_rules(record: dict[str, Any]) -> list[RuleResult]:
    """Run every business rule against a record. Returns a list of RuleResult."""
    results: list[RuleResult] = []
    policies = get_policies()

    # ── Required fields ───────────────────────────────────────────────────────
    for req_field in policies["required_fields"]:
        val = record.get(req_field)
        if val is None or val == "" or val == "N/A" or val == "Unknown":
            results.append(RuleResult(
                field=req_field,
                passed=False,
                message=f"Required field '{req_field}' is missing or empty.",
                severity="error",
            ))
        else:
            results.append(RuleResult(
                field=req_field,
                passed=True,
                message=f"'{req_field}' is present.",
                severity="info",
            ))

    # ── Summary word count ────────────────────────────────────────────────────
    summary = record.get("summary", "")
    word_count = len(summary.split()) if summary else 0
    min_w = policies["summary_min_words"]
    max_w = policies["summary_max_words"]
    if word_count < min_w:
        results.append(RuleResult(
            field="summary",
            passed=False,
            message=f"Summary too short ({word_count} words; minimum {min_w}).",
            severity="warning",
        ))
    elif word_count > max_w:
        results.append(RuleResult(
            field="summary",
            passed=False,
            message=f"Summary too long ({word_count} words; maximum {max_w}).",
            severity="warning",
        ))
    else:
        results.append(RuleResult(
            field="summary",
            passed=True,
            message=f"Summary word count OK ({word_count} words).",
            severity="info",
        ))

    # ── Sentiment score range ─────────────────────────────────────────────────
    lo, hi = policies["sentiment_score_range"]
    for score_field in ["customer_sentiment_score", "agent_sentiment_score"]:
        score = record.get(score_field)
        if score is None:
            continue
        try:
            score = float(score)
            if not (lo <= score <= hi):
                results.append(RuleResult(
                    field=score_field,
                    passed=False,
                    message=f"'{score_field}' value {score} is outside [{lo}, {hi}].",
                    severity="error",
                ))
            else:
                results.append(RuleResult(
                    field=score_field,
                    passed=True,
                    message=f"'{score_field}' = {score:.2f} is in valid range.",
                    severity="info",
                ))
        except (TypeError, ValueError):
            results.append(RuleResult(
                field=score_field,
                passed=False,
                message=f"'{score_field}' is not a number: {score!r}.",
                severity="error",
            ))

    # ── Sentiment label validity ──────────────────────────────────────────────
    for sent_field in ["customer_sentiment", "agent_sentiment"]:
        label = record.get(sent_field, "")
        if label and not lookup_sentiment(label):
            results.append(RuleResult(
                field=sent_field,
                passed=False,
                message=f"'{sent_field}' value '{label}' is not a recognised sentiment label.",
                severity="error",
            ))

    # ── Sentiment-score direction consistency ─────────────────────────────────
    cust_label = record.get("customer_sentiment", "")
    cust_score = record.get("customer_sentiment_score")
    if cust_label and cust_score is not None:
        try:
            cust_score = float(cust_score)
            inconsistent = (
                (cust_label == "Positive" and cust_score < 0) or
                (cust_label == "Negative" and cust_score > 0)
            )
            if inconsistent:
                results.append(RuleResult(
                    field="customer_sentiment",
                    passed=False,
                    message=(
                        f"Contradiction: customer_sentiment='{cust_label}' "
                        f"but score={cust_score:.2f} points in the opposite direction."
                    ),
                    severity="error",
                ))
        except (TypeError, ValueError):
            pass

    # ── Tonality validity ─────────────────────────────────────────────────────
    tonality = record.get("tonality", "")
    if tonality and not lookup_tonality(tonality):
        results.append(RuleResult(
            field="tonality",
            passed=False,
            message=f"Tonality '{tonality}' is not a recognised value.",
            severity="warning",
        ))

    # ── Resolution validity ───────────────────────────────────────────────────
    resolution = record.get("resolution", "")
    if resolution and not lookup_resolution(resolution):
        results.append(RuleResult(
            field="resolution",
            passed=False,
            message=f"Resolution '{resolution}' is not a recognised status.",
            severity="error",
        ))

    # ── Escalated calls must not be marked Resolved ───────────────────────────
    if resolution == "Resolved" and "escalat" in record.get("action_taken", "").lower():
        results.append(RuleResult(
            field="resolution",
            passed=False,
            message="Resolution is 'Resolved' but action_taken mentions escalation — likely incorrect.",
            severity="error",
        ))

    return results
