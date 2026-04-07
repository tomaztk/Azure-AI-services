"""
analyzer.py
-----------
Orchestrates the agentic analysis of a transcribed call using
Azure AI Foundry (azure.ai.projects).

Architecture
------------
1.  An AIProjectClient is created from the project endpoint.
2.  A FunctionTool is built from the local Python functions in tools.py.
3.  An agent is created (or reused) with those tools and a QA-analyst persona.
4.  A new thread is opened per call; the transcript is posted as the first user message.
5.  The agent decides which tools to call and in what order; the SDK's
    create_and_process() handles the tool-call loop automatically.
6.  The final assistant message is parsed to extract a structured result dict.
7.  The agent and thread are cleaned up after each run.

Env vars required
-----------------
  AZURE_AI_PROJECT_ENDPOINT    — e.g. https://<resource>.services.ai.azure.com/api/projects/<project>
  AZURE_AI_MODEL_DEPLOYMENT    — deployment name of the chat model (e.g. gpt-4o)
"""

import json
import os
import re

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, ToolSet
from azure.identity import DefaultAzureCredential

from tools import TOOL_FUNCTIONS


# ── System prompt for the call-centre QA orchestrator agent ─────────────────
_SYSTEM_PROMPT = """
You are a call centre quality assurance analyst. You have received the transcript
of a recorded phone call between a customer and a support agent.

Your job is to analyse this call thoroughly by calling EACH of the following tools
(in order, without skipping any):

  1. extract_summary          — pass the full transcript
  2. classify_product         — pass the full transcript
  3. analyze_customer_sentiment — pass only the customer's lines
  4. analyze_agent_sentiment    — pass only the agent's lines
  5. detect_tonality          — pass the full transcript
  6. identify_service         — pass the full transcript

After calling all six tools, return a SINGLE JSON object (no markdown fences)
with these exact top-level keys:

{
  "summary":            "<output of extract_summary>",
  "product_L1":         "<L1 from classify_product>",
  "product_L2":         "<L2 from classify_product>",
  "product_L3":         "<L3 from classify_product>",
  "customer_sentiment": "<sentiment from analyze_customer_sentiment>",
  "customer_sentiment_score": <score from analyze_customer_sentiment>,
  "customer_sentiment_reasoning": "<reasoning>",
  "agent_sentiment":    "<sentiment from analyze_agent_sentiment>",
  "agent_sentiment_score": <score from analyze_agent_sentiment>,
  "agent_sentiment_reasoning": "<reasoning>",
  "tonality":           "<tonality from detect_tonality>",
  "tonality_descriptors": ["<d1>", "<d2>"],
  "service":            "<service from identify_service>",
  "action_taken":       "<action_taken from identify_service>",
  "resolution":         "<resolution from identify_service>"
}

Do not add commentary outside the JSON object.
""".strip()


def _build_user_message(transcript: dict) -> str:
    """Format the transcript dict into the agent's first user message."""
    lines = [
        "## FULL TRANSCRIPT (labelled by speaker)\n",
        transcript["full_text"],
        "\n\n## CUSTOMER LINES ONLY\n",
        transcript["customer_text"] or "(no customer lines detected)",
        "\n\n## AGENT LINES ONLY\n",
        transcript["agent_text"] or "(no agent lines detected)",
    ]
    return "\n".join(lines)


def _extract_json_from_text(text: str) -> dict:
    """
    Try to extract a JSON object from the agent's final message.
    Falls back to an empty dict if parsing fails.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?", "", text).strip()

    # Try to find the first {...} block
    match = re.search(r"\{[\s\S]+\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def analyze_call(audio_file: str, transcript: dict) -> dict:
    """
    Run the full agentic analysis pipeline on the transcribed call.

    Parameters
    ----------
    audio_file : str
        Path to the original audio file (used for logging only).
    transcript : dict
        Output of transcriber.transcribe_audio().

    Returns
    -------
    dict
        Flat dict with all analysis fields, ready for CSV export.
    """
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]

    project_client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )

    model = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]

    # ── Build FunctionTool from local Python functions ───────────────────────
    functions = FunctionTool(functions=set(TOOL_FUNCTIONS.values()))
    toolset = ToolSet()
    toolset.add(functions)

    agent = None
    thread = None

    try:
        # ── Create the QA orchestrator agent ────────────────────────────────
        agent = project_client.agents.create_agent(
            model=model,
            name="call-center-qa-agent",
            instructions=_SYSTEM_PROMPT,
            toolset=toolset,
        )
        print(f"      Agent created  → {agent.id}")

        # ── Open a thread and post the transcript ────────────────────────────
        thread = project_client.agents.threads.create()
        print(f"      Thread created → {thread.id}")

        user_message = _build_user_message(transcript)
        project_client.agents.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_message,
        )

        # ── Run the agent (handles tool-call loop automatically) ─────────────
        run = project_client.agents.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent.id,
        )
        print(f"      Run finished   → status={run.status}")

        if run.status == "failed":
            print(f"      [WARN] Run failed: {run.last_error}")
            return _fallback_result()

        # ── Extract the assistant's final message ────────────────────────────
        messages = list(project_client.agents.messages.list(thread_id=thread.id))

        # Messages are newest-first; find the last assistant message
        assistant_text = ""
        for msg in messages:
            if msg.role == "assistant":
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        assistant_text = block.text.value
                        break
                if assistant_text:
                    break

        raw_result = _extract_json_from_text(assistant_text)
        return _normalise_result(raw_result)

    finally:
        # ── Cleanup ─────────────────────────────────────────────────────────
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


def _normalise_result(raw: dict) -> dict:
    """
    Ensure all expected keys are present with sensible defaults.
    """
    defaults = {
        "summary": "N/A",
        "product_L1": "Unknown",
        "product_L2": "Unknown",
        "product_L3": "Unknown",
        "customer_sentiment": "Unknown",
        "customer_sentiment_score": 0.0,
        "customer_sentiment_reasoning": "",
        "agent_sentiment": "Unknown",
        "agent_sentiment_score": 0.0,
        "agent_sentiment_reasoning": "",
        "tonality": "Unknown",
        "tonality_descriptors": [],
        "service": "Unknown",
        "action_taken": "",
        "resolution": "Unknown",
    }
    result = {**defaults, **raw}

    # Flatten tonality_descriptors list → comma-separated string for CSV
    descriptors = result.get("tonality_descriptors", [])
    if isinstance(descriptors, list):
        result["tonality_descriptors"] = ", ".join(descriptors)

    return result


def _fallback_result() -> dict:
    """Return an empty result structure when the agent run fails."""
    return _normalise_result({})
