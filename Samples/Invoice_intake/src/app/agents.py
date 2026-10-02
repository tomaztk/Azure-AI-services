"""Calls the Foundry prompt agents through the Responses API (azure-ai-projects 2.x).

- review_invoice(): the invoice review agent returns a JSON opinion (structured output).
- ask(): the sales agent answers audience questions with function tools that run SQL here,
  under the persona's row-level security.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.responses.response_input_param import FunctionCallOutput

from . import sales_tools
from .agent_definitions import PERSONAS
from .config import get_settings
from .rules import ReviewOpinion

log = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 6
MAX_DOCUMENT_CHARS = 6000


class AgentService:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        self.project = AIProjectClient(endpoint=s.foundry_project_endpoint, credential=DefaultAzureCredential())
        self.openai = self.project.get_openai_client()

    def _agent_ref(self, name: str) -> dict[str, Any]:
        return {"agent_reference": {"name": name, "type": "agent_reference"}}

    # ------------------------------------------------------------------ invoice review
    def review_invoice(self, trusted_context: dict[str, Any], document_text: str) -> ReviewOpinion:
        """Second opinion on an invoice. Raises on failure; the caller routes to a human then."""
        prompt = (
            "Review this supplier invoice.\n\n"
            "<trusted_context>\n" + json.dumps(trusted_context, default=str, indent=1) + "\n</trusted_context>\n\n"
            "<untrusted_document_text>\n" + (document_text or "")[:MAX_DOCUMENT_CHARS] + "\n</untrusted_document_text>"
        )
        try:
            response = self.openai.responses.create(
                input=prompt, extra_body=self._agent_ref(self.settings.review_agent_name))
        except Exception as ex:
            # A Foundry guardrail (content filter / prompt shield) blocking the request is itself a signal.
            if "content_filter" in str(ex) or "ResponsibleAIPolicyViolation" in str(ex):
                return ReviewOpinion(recommendation="review", injection_detected=True,
                                     summary="Blocked by the Foundry guardrail (suspicious content in the document).")
            raise
        data = json.loads(response.output_text)
        return ReviewOpinion(
            recommendation=str(data.get("recommendation", "review")).lower(),
            summary=str(data.get("summary", ""))[:500],
            concerns=[str(c)[:200] for c in data.get("concerns", [])][:6],
            injection_detected=bool(data.get("injection_detected")),
            manual_alteration_detected=bool(data.get("manual_alteration_detected")),
            not_an_invoice=bool(data.get("not_an_invoice")),
        )

    # ------------------------------------------------------------------ sales Q&A
    def ask(self, question: str, persona: str, conversation_id: str | None = None) -> dict[str, Any]:
        started = time.monotonic()
        if persona not in PERSONAS:
            persona = "cfo"
        if not conversation_id:
            conversation_id = self.openai.conversations.create().id
        context = (f"[Context: user role = {PERSONAS[persona]}; sales data as of {sales_tools.sales_as_of()}; "
                   f"today is {time.strftime('%Y-%m-%d')}]\n")
        ref = self._agent_ref(self.settings.sales_agent_name)
        response = self.openai.responses.create(conversation=conversation_id, input=context + question, extra_body=ref)

        tools_used: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                break
            outputs = []
            for call in calls:
                tools_used.append(call.name)
                result = sales_tools.execute(call.name, call.arguments, persona)
                outputs.append(FunctionCallOutput(type="function_call_output", call_id=call.call_id, output=result))
            response = self.openai.responses.create(conversation=conversation_id, input=outputs, extra_body=ref)

        return {
            "answer": response.output_text or "Sorry, I couldn't find an answer.",
            "conversation_id": conversation_id,
            "tools": tools_used,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
