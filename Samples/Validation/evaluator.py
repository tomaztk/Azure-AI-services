"""
evaluator.py
------------
Layer 4 — Groundedness & quality scoring using the Azure AI Evaluation SDK
(azure.ai.evaluation).

We measure:
  • Groundedness   — is the summary supported by the call transcript?
  • Relevance      — is the extracted information relevant to the query context?
  • Coherence      — is the summary internally coherent?

All scores are 1–5.  A score < 3 triggers a validation warning.

Env vars required (same as main project):
  AZURE_ENDPOINT              — Azure OpenAI endpoint
  AZURE_AI_API_KEY            — Azure OpenAI key
  AZURE_AI_MODEL_DEPLOYMENT   — GPT-4o deployment name
  AZURE_API_VERSION           — e.g. 2024-12-01-preview
"""

from __future__ import annotations
import os
from dataclasses import dataclass

from azure.ai.evaluation import (
    GroundednessEvaluator,
    RelevanceEvaluator,
    CoherenceEvaluator,
    AzureOpenAIModelConfiguration,
)


@dataclass
class EvalResult:
    groundedness_score: float | None = None
    groundedness_reason: str = ""
    relevance_score: float | None = None
    coherence_score: float | None = None
    passed: bool = True
    issues: list[str] = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


def _get_model_config() -> AzureOpenAIModelConfiguration:
    return AzureOpenAIModelConfiguration(
        azure_endpoint=os.environ["AZURE_ENDPOINT"],
        api_key=os.environ.get("AZURE_AI_API_KEY"),
        azure_deployment=os.environ["AZURE_AI_MODEL_DEPLOYMENT"],
        api_version=os.environ.get("AZURE_API_VERSION", "2024-12-01-preview"),
    )


def evaluate_groundedness(
    summary: str,
    transcript: str,
    query: str = "Summarise this call centre recording.",
) -> EvalResult:
    """
    Evaluate whether the AI-generated summary is grounded in the transcript.

    Parameters
    ----------
    summary    : The AI-generated summary to validate.
    transcript : The source call transcript (the "ground truth" context).
    query      : The original task instruction given to the AI.

    Returns
    -------
    EvalResult with per-metric scores and a list of issues.
    """
    result = EvalResult()

    try:
        model_config = _get_model_config()

        # ── Groundedness ──────────────────────────────────────────────────────
        ground_eval = GroundednessEvaluator(model_config)
        ground_out = ground_eval(
            query=query,
            response=summary,
            context=transcript,
        )
        result.groundedness_score = ground_out.get("groundedness", None)
        result.groundedness_reason = ground_out.get("groundedness_reason", "")

        # ── Relevance ─────────────────────────────────────────────────────────
        rel_eval = RelevanceEvaluator(model_config)
        rel_out = rel_eval(
            query=query,
            response=summary,
            context=transcript,
        )
        result.relevance_score = rel_out.get("relevance", None)

        # ── Coherence ─────────────────────────────────────────────────────────
        coh_eval = CoherenceEvaluator(model_config)
        coh_out = coh_eval(query=query, response=summary)
        result.coherence_score = coh_out.get("coherence", None)

    except Exception as exc:
        result.issues.append(f"Evaluator error: {exc}")
        result.passed = False
        return result

    # ── Determine pass/fail ───────────────────────────────────────────────────
    THRESHOLD = 3.0

    if result.groundedness_score is not None and result.groundedness_score < THRESHOLD:
        result.issues.append(
            f"Low groundedness score ({result.groundedness_score:.1f}/5) — "
            f"summary may contain hallucinations. Reason: {result.groundedness_reason}"
        )
        result.passed = False

    if result.relevance_score is not None and result.relevance_score < THRESHOLD:
        result.issues.append(
            f"Low relevance score ({result.relevance_score:.1f}/5) — "
            "extracted content may not match the actual call topic."
        )
        result.passed = False

    if result.coherence_score is not None and result.coherence_score < THRESHOLD:
        result.issues.append(
            f"Low coherence score ({result.coherence_score:.1f}/5) — "
            "summary may be incoherent or poorly structured."
        )
        result.passed = False

    return result
