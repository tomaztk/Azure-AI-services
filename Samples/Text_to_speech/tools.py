"""
tools.py
--------
Python functions that are registered as FunctionTool definitions for the
Azure AI Foundry agent.  Each function uses the project's OpenAI client
to perform a single, focused extraction task on the call transcript.

All functions share the same signature contract expected by FunctionTool:
  - They are regular (sync) Python callables
  - Parameters are simple JSON-serialisable types
  - Return value is always a string (the agent reads it as tool output)
"""

import json
import os
from typing import Any

# ── Shared OpenAI client (initialised lazily) ───────────────────────────────
_openai_client: Any = None
_model_name: str = ""


def _get_openai_client():
    """Return a cached Azure OpenAI client obtained via AIProjectClient."""
    global _openai_client, _model_name
    if _openai_client is None:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        project = AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=DefaultAzureCredential(),
        )
        _openai_client = project.get_openai_client()
        _model_name = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]
    return _openai_client, _model_name


def _call_llm(system_prompt: str, user_content: str) -> str:
    """Helper: single-turn LLM call, returns the assistant text."""
    client, model = _get_openai_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
        max_tokens=512,
    )
    return response.choices[0].message.content.strip()


# ══════════════════════════════════════════════════════════════════════════════
# Tool functions — the agent calls these by name
# ══════════════════════════════════════════════════════════════════════════════


def extract_summary(transcript: str) -> str:
    """
    Generate a concise summary (3-5 sentences) of the call.

    Args:
        transcript: Full labelled transcript of the call.

    Returns:
        A short plain-text summary.
    """
    return _call_llm(
        system_prompt=(
            "You are an expert call center quality analyst. "
            "Summarise the following call transcript in 3-5 concise sentences. "
            "Focus on: what the customer needed, what actions were taken, and the outcome."
        ),
        user_content=f"TRANSCRIPT:\n{transcript}",
    )


def classify_product(transcript: str) -> str:
    """
    Classify the product or service discussed in the call into a three-level
    hierarchy (L1 → L2 → L3).

    Args:
        transcript: Full labelled transcript of the call.

    Returns:
        JSON string: {"L1": "...", "L2": "...", "L3": "..."}
    """
    raw = _call_llm(
        system_prompt=(
            "You are a call center taxonomy expert. "
            "Analyse the transcript and classify the product/service into a 3-level hierarchy.\n"
            "Return ONLY valid JSON with keys: L1, L2, L3.\n"
            "Use generic business categories where specific info is missing.\n"
            "Example: {\"L1\": \"Banking\", \"L2\": \"Credit Card\", \"L3\": \"Payment Dispute\"}"
        ),
        user_content=f"TRANSCRIPT:\n{transcript}",
    )
    # Validate / sanitise JSON
    try:
        obj = json.loads(raw)
        return json.dumps({k: obj.get(k, "N/A") for k in ["L1", "L2", "L3"]})
    except json.JSONDecodeError:
        return json.dumps({"L1": "Unknown", "L2": "Unknown", "L3": "Unknown"})


def analyze_customer_sentiment(customer_transcript: str) -> str:
    """
    Analyse the sentiment expressed by the customer across the call.

    Args:
        customer_transcript: Customer-only lines from the transcript.

    Returns:
        JSON string: {"sentiment": "Positive|Neutral|Negative|Mixed",
                      "score": float (-1.0 … 1.0), "reasoning": "..."}
    """
    raw = _call_llm(
        system_prompt=(
            "You are a sentiment analysis expert. "
            "Analyse the customer's sentiment from their utterances in this call.\n"
            "Return ONLY valid JSON with keys:\n"
            "  sentiment: one of Positive | Neutral | Negative | Mixed\n"
            "  score: float between -1.0 (most negative) and 1.0 (most positive)\n"
            "  reasoning: one sentence explaining the score"
        ),
        user_content=f"CUSTOMER UTTERANCES:\n{customer_transcript}",
    )
    try:
        obj = json.loads(raw)
        return json.dumps(
            {
                "sentiment": obj.get("sentiment", "Unknown"),
                "score": round(float(obj.get("score", 0.0)), 2),
                "reasoning": obj.get("reasoning", ""),
            }
        )
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"sentiment": "Unknown", "score": 0.0, "reasoning": ""})


def analyze_agent_sentiment(agent_transcript: str) -> str:
    """
    Analyse the sentiment and professionalism of the agent across the call.

    Args:
        agent_transcript: Agent-only lines from the transcript.

    Returns:
        JSON string: {"sentiment": "Positive|Neutral|Negative|Mixed",
                      "score": float, "reasoning": "..."}
    """
    raw = _call_llm(
        system_prompt=(
            "You are a call center QA specialist. "
            "Analyse the agent's tone and sentiment from their utterances.\n"
            "Return ONLY valid JSON with keys:\n"
            "  sentiment: one of Positive | Neutral | Negative | Mixed\n"
            "  score: float between -1.0 and 1.0\n"
            "  reasoning: one sentence explaining the score"
        ),
        user_content=f"AGENT UTTERANCES:\n{agent_transcript}",
    )
    try:
        obj = json.loads(raw)
        return json.dumps(
            {
                "sentiment": obj.get("sentiment", "Unknown"),
                "score": round(float(obj.get("score", 0.0)), 2),
                "reasoning": obj.get("reasoning", ""),
            }
        )
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"sentiment": "Unknown", "score": 0.0, "reasoning": ""})


def detect_tonality(transcript: str) -> str:
    """
    Detect the overall tonality of the interaction.

    Args:
        transcript: Full labelled transcript.

    Returns:
        JSON string: {"tonality": "...", "descriptors": [...], "reasoning": "..."}
    """
    raw = _call_llm(
        system_prompt=(
            "You are a communication quality expert. "
            "Assess the overall tonality of this call centre interaction.\n"
            "Return ONLY valid JSON with keys:\n"
            "  tonality: one of Formal | Informal | Empathetic | Tense | "
            "Neutral | Confrontational | Friendly | Professional\n"
            "  descriptors: array of 2-4 adjectives that best describe the tone\n"
            "  reasoning: one sentence"
        ),
        user_content=f"TRANSCRIPT:\n{transcript}",
    )
    try:
        obj = json.loads(raw)
        return json.dumps(
            {
                "tonality": obj.get("tonality", "Unknown"),
                "descriptors": obj.get("descriptors", []),
                "reasoning": obj.get("reasoning", ""),
            }
        )
    except json.JSONDecodeError:
        return json.dumps(
            {"tonality": "Unknown", "descriptors": [], "reasoning": ""}
        )


def identify_service(transcript: str) -> str:
    """
    Identify the primary service action performed during the call.

    Args:
        transcript: Full labelled transcript.

    Returns:
        JSON string: {"service": "...", "action_taken": "...", "resolution": "Resolved|Unresolved|Escalated|Pending"}
    """
    raw = _call_llm(
        system_prompt=(
            "You are a call center operations analyst. "
            "Identify the primary service performed and the resolution status.\n"
            "Return ONLY valid JSON with keys:\n"
            "  service: short label for the type of service (e.g. 'Account Inquiry', "
            "'Technical Support', 'Billing Dispute', 'Order Management', etc.)\n"
            "  action_taken: one sentence describing what the agent did\n"
            "  resolution: one of Resolved | Unresolved | Escalated | Pending"
        ),
        user_content=f"TRANSCRIPT:\n{transcript}",
    )
    try:
        obj = json.loads(raw)
        return json.dumps(
            {
                "service": obj.get("service", "Unknown"),
                "action_taken": obj.get("action_taken", ""),
                "resolution": obj.get("resolution", "Unknown"),
            }
        )
    except json.JSONDecodeError:
        return json.dumps(
            {"service": "Unknown", "action_taken": "", "resolution": "Unknown"}
        )


# ── Registry used by analyzer.py to build the FunctionTool ──────────────────
TOOL_FUNCTIONS = {
    "extract_summary": extract_summary,
    "classify_product": classify_product,
    "analyze_customer_sentiment": analyze_customer_sentiment,
    "analyze_agent_sentiment": analyze_agent_sentiment,
    "detect_tonality": detect_tonality,
    "identify_service": identify_service,
}
