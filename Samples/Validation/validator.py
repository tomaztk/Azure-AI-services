"""
validator.py
------------
Core orchestrator: runs all 5 validation layers for a single record.

Layer 1  Schema & Completeness   — deterministic (rules_engine)
Layer 2  Business Rules          — deterministic (rules_engine)
Layer 3  Knowledge-Base Lookup   — deterministic (knowledge_base)
Layer 4  Groundedness (AI eval)  — azure.ai.evaluation SDK
Layer 5  Contradiction Detection — Azure AI Foundry agent (AIProjectClient)

Returns a ValidationReport dataclass used by reporter.py.
"""

from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

from rules_engine import run_all_rules, RuleResult
from knowledge_base import (
    lookup_product_taxonomy,
    lookup_service,
    kb_as_json,
)


# ══════════════════════════════════════════════════════════════════════════════
# Data model
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationReport:
    record_id: str
    validated_at: str
    original_record: dict

    # Layer results
    schema_issues: list[RuleResult] = field(default_factory=list)
    rules_issues: list[RuleResult] = field(default_factory=list)
    kb_issues: list[str] = field(default_factory=list)
    eval_scores: dict = field(default_factory=dict)
    eval_issues: list[str] = field(default_factory=list)
    agent_findings: list[str] = field(default_factory=list)

    # Overall verdict
    overall_status: str = "PASS"     # PASS | WARN | FAIL
    confidence: float = 1.0          # 0.0–1.0
    corrected_fields: dict = field(default_factory=dict)  # agent-suggested corrections


# ══════════════════════════════════════════════════════════════════════════════
# Layer 5 — Azure AI Foundry agent (contradiction detection + corrections)
# ══════════════════════════════════════════════════════════════════════════════

# Agent-callable tools (run locally, results returned to agent as strings)

def check_taxonomy_validity(l1: str, l2: str, l3: str) -> str:
    """
    Verify that (L1, L2, L3) form a valid product taxonomy path.

    Args:
        l1: Top-level product category (e.g. 'Banking').
        l2: Sub-category (e.g. 'Credit Card').
        l3: Specific issue (e.g. 'Payment Dispute').

    Returns:
        JSON string with keys: full_path_valid, valid_l1, valid_l2, valid_l3, suggestions.
    """
    return json.dumps(lookup_product_taxonomy(l1, l2, l3))


def check_service_label(service: str) -> str:
    """
    Check whether the service label is recognised in the knowledge base.

    Args:
        service: The service label to check (e.g. 'Billing Dispute').

    Returns:
        JSON string with keys: exact_match, close_matches.
    """
    return json.dumps(lookup_service(service))


def assess_internal_consistency(record_json: str) -> str:
    """
    Check the record fields for internal contradictions.

    Args:
        record_json: JSON string of the full record to inspect.

    Returns:
        JSON string with keys: contradictions (list of str), consistent (bool).
    """
    try:
        record = json.loads(record_json)
    except json.JSONDecodeError:
        return json.dumps({"contradictions": ["Invalid JSON input"], "consistent": False})

    contradictions = []

    # Sentiment vs tonality alignment
    cust_sent = record.get("customer_sentiment", "")
    tonality = record.get("tonality", "")
    if cust_sent == "Positive" and tonality in ["Confrontational", "Tense"]:
        contradictions.append(
            f"customer_sentiment='{cust_sent}' conflicts with tonality='{tonality}'"
        )

    # Escalated resolution vs resolved claim
    resolution = record.get("resolution", "")
    action = record.get("action_taken", "")
    if resolution == "Resolved" and "escalat" in action.lower():
        contradictions.append(
            "resolution='Resolved' but action_taken describes an escalation"
        )

    # Negative customer sentiment with Positive agent sentiment when unresolved
    agent_sent = record.get("agent_sentiment", "")
    if (cust_sent == "Negative" and agent_sent == "Positive" and resolution == "Unresolved"):
        contradictions.append(
            "Customer is Negative, agent is Positive, but call was Unresolved — "
            "check if agent sentiment was correctly classified"
        )

    # Summary mentions vs extracted service
    summary = record.get("summary", "").lower()
    service = record.get("service", "").lower()
    # Simple keyword cross-check
    if "fraud" in summary and "fraud" not in service and "fraud" not in record.get("product_L3", "").lower():
        contradictions.append(
            "Summary mentions 'fraud' but neither service nor product_L3 reflects this"
        )

    return json.dumps({
        "contradictions": contradictions,
        "consistent": len(contradictions) == 0,
    })


def suggest_correction(field_name: str, current_value: str, reason: str) -> str:
    """
    Propose a corrected value for a field that failed validation.

    Args:
        field_name: The name of the field to correct (e.g. 'resolution').
        current_value: The currently extracted value.
        reason: Why this field is believed to be incorrect.

    Returns:
        JSON string with keys: field, current_value, suggested_value, confidence.
    """
    # The agent itself will fill in suggested_value — this is a stub that the
    # agent populates by reasoning from the transcript and KB context.
    return json.dumps({
        "field": field_name,
        "current_value": current_value,
        "suggested_value": "__AGENT_WILL_PROVIDE__",
        "confidence": 0.0,
        "reason": reason,
    })


_AGENT_TOOLS = {
    check_taxonomy_validity,
    check_service_label,
    assess_internal_consistency,
    suggest_correction,
}

_AGENT_SYSTEM_PROMPT = """
You are an enterprise data quality agent. Your task is to deeply validate a JSON
record that was produced by an AI extraction pipeline.

You have access to four tools:
  • check_taxonomy_validity(l1, l2, l3) — verifies the product taxonomy path
  • check_service_label(service)        — verifies the service label vs the KB
  • assess_internal_consistency(record_json) — finds logical contradictions
  • suggest_correction(field, value, reason) — proposes a corrected value

Workflow (follow this order):
  1. Call check_taxonomy_validity with the L1, L2, L3 values from the record.
  2. Call check_service_label with the service field.
  3. Call assess_internal_consistency with the FULL record as JSON.
  4. For any field that is invalid or contradictory, call suggest_correction.
  5. After all tool calls, respond with a SINGLE JSON object (no markdown):

{
  "findings": ["<finding 1>", "<finding 2>", ...],
  "corrected_fields": {
    "<field_name>": {"suggested_value": "...", "confidence": 0.0-1.0, "reason": "..."}
  },
  "agent_confidence": 0.0-1.0
}

Be concise. If everything is valid, return an empty findings list and empty corrected_fields.
""".strip()


def _run_agent_layer(record: dict) -> dict:
    """
    Run the Azure AI Foundry agent (Layer 5).
    Returns the parsed JSON from the agent's final message.
    """
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]

    project_client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )

    functions = FunctionTool(functions=_AGENT_TOOLS)
    toolset = ToolSet()
    toolset.add(functions)

    agent = thread = None
    try:
        agent = project_client.agents.create_agent(
            model=model,
            name="info-validation-agent",
            instructions=_AGENT_SYSTEM_PROMPT,
            toolset=toolset,
        )

        thread = project_client.agents.threads.create()

        # Post the record as the user message
        kb_summary = "Available KB: see agent instructions for taxonomy."
        user_msg = (
            f"Please validate this extracted record:\n\n"
            f"```json\n{json.dumps(record, indent=2)}\n```\n\n"
            f"{kb_summary}"
        )
        project_client.agents.messages.create(
            thread_id=thread.id, role="user", content=user_msg
        )

        run = project_client.agents.runs.create_and_process(
            thread_id=thread.id, agent_id=agent.id
        )

        if run.status == "failed":
            return {"findings": [f"Agent run failed: {run.last_error}"], "corrected_fields": {}, "agent_confidence": 0.0}

        # Extract assistant message
        messages = list(project_client.agents.messages.list(thread_id=thread.id))
        text = ""
        for msg in messages:
            if msg.role == "assistant":
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        text = block.text.value
                        break
                if text:
                    break

        # Parse JSON from text
        match = re.search(r"\{[\s\S]+\}", text.replace("```json", "").replace("```", ""))
        if match:
            return json.loads(match.group())
        return {"findings": [text], "corrected_fields": {}, "agent_confidence": 0.5}

    except Exception as exc:
        return {"findings": [f"Agent error: {exc}"], "corrected_fields": {}, "agent_confidence": 0.0}
    finally:
        if thread:
            try:
                project_client.agents.threads.delete(thread.id)
            except Exception:
                pass
        if agent:
            try:
                project_client.agents.delete_agent(agent.id)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# Main public function
# ══════════════════════════════════════════════════════════════════════════════

def validate_record(record: dict[str, Any]) -> ValidationReport:
    """
    Run all 5 validation layers and return a ValidationReport.
    """
    report = ValidationReport(
        record_id=record.get("audio_file", "unknown"),
        validated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        original_record=record,
    )

    # ── Layer 1 & 2: Schema + Business Rules ──────────────────────────────────
    print("      [Layer 1/2] Schema & business rules …", end=" ", flush=True)
    rule_results = run_all_rules(record)
    errors = [r for r in rule_results if not r.passed and r.severity == "error"]
    warnings = [r for r in rule_results if not r.passed and r.severity == "warning"]
    report.schema_issues = errors
    report.rules_issues = warnings
    print(f"{'✓' if not errors else '✗'} ({len(errors)} errors, {len(warnings)} warnings)")

    # ── Layer 3: KB Lookup ────────────────────────────────────────────────────
    print("      [Layer 3]   Knowledge-base lookup …", end=" ", flush=True)
    kb_issues = []
    tax = lookup_product_taxonomy(
        record.get("product_L1", ""),
        record.get("product_L2", ""),
        record.get("product_L3", ""),
    )
    if not tax["full_path_valid"]:
        kb_issues.append(
            f"Product taxonomy path is invalid. "
            f"L1 valid={tax['valid_l1']}, L2 valid={tax['valid_l2']}, L3 valid={tax['valid_l3']}. "
            f"Suggestions: {tax['suggestions']}"
        )
    svc = lookup_service(record.get("service", ""))
    if not svc["exact_match"]:
        close = svc.get("close_matches", [])
        kb_issues.append(
            f"Service label '{record.get('service')}' not in KB. "
            f"Close matches: {close or 'none'}."
        )
    report.kb_issues = kb_issues
    print(f"{'✓' if not kb_issues else '✗'} ({len(kb_issues)} issues)")

    # ── Layer 4: Groundedness (AI Evaluation SDK) ─────────────────────────────
    summary = record.get("summary", "")
    transcript = record.get("_transcript", "")  # optional — attached by pipeline

    if summary and transcript:
        print("      [Layer 4]   Groundedness evaluation …", end=" ", flush=True)
        try:
            from evaluator import evaluate_groundedness
            eval_result = evaluate_groundedness(summary=summary, transcript=transcript)
            report.eval_scores = {
                "groundedness": eval_result.groundedness_score,
                "relevance": eval_result.relevance_score,
                "coherence": eval_result.coherence_score,
            }
            report.eval_issues = eval_result.issues
            print(f"{'✓' if eval_result.passed else '✗'} "
                  f"(g={eval_result.groundedness_score}, "
                  f"r={eval_result.relevance_score}, "
                  f"c={eval_result.coherence_score})")
        except Exception as e:
            print(f"⚠ skipped ({e})")
    else:
        print("      [Layer 4]   Groundedness evaluation … ⚠ skipped (no transcript attached)")

    # ── Layer 5: Agent — contradiction detection ──────────────────────────────
    print("      [Layer 5]   Agent contradiction detection …", end=" ", flush=True)
    agent_output = _run_agent_layer(record)
    report.agent_findings = agent_output.get("findings", [])
    report.corrected_fields = agent_output.get("corrected_fields", {})
    agent_conf = agent_output.get("agent_confidence", 1.0)
    print(f"{'✓' if not report.agent_findings else '✗'} ({len(report.agent_findings)} findings)")

    # ── Overall verdict ───────────────────────────────────────────────────────
    total_errors = len(report.schema_issues) + len(report.kb_issues) + len(report.eval_issues)
    total_warnings = len(report.rules_issues) + len(report.agent_findings)

    if total_errors > 0:
        report.overall_status = "FAIL"
    elif total_warnings > 0:
        report.overall_status = "WARN"
    else:
        report.overall_status = "PASS"

    # Confidence: weighted combination of rule pass-rate and agent confidence
    n_rules = len(rule_results)
    rule_pass_rate = sum(1 for r in rule_results if r.passed) / n_rules if n_rules else 1.0
    report.confidence = round((rule_pass_rate * 0.6 + agent_conf * 0.4), 2)

    return report
