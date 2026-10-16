"""Calls the Foundry data agent through the Responses API (azure-ai-projects 2.x).

The agent decides which function tools to call; this module runs them against Azure SQL
(data_tools.py), hands the rows back to the agent and returns its answer.
"""
from __future__ import annotations

import time
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.responses.response_input_param import FunctionCallOutput

from . import data_tools
from .config import get_settings

MAX_TOOL_ROUNDS = 6


class AgentService:
    def __init__(self) -> None:
        s = get_settings()
        self.agent_name = s.agent_name
        self.project = AIProjectClient(endpoint=s.foundry_project_endpoint, credential=DefaultAzureCredential())
        self.openai = self.project.get_openai_client()

    def ask(self, question: str, conversation_id: str | None = None) -> dict[str, Any]:
        started = time.monotonic()
        if not conversation_id:
            conversation_id = self.openai.conversations.create().id
        ref = {"agent_reference": {"name": self.agent_name, "type": "agent_reference"}}
        context = (f"[Context: today is {time.strftime('%Y-%m-%d')}; "
                   f"sales data as of {data_tools.sales_as_of()}]\n")
        response = self.openai.responses.create(conversation=conversation_id, input=context + question, extra_body=ref)

        tools_used: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                break
            outputs = []
            for call in calls:
                tools_used.append(call.name)
                result = data_tools.execute(call.name, call.arguments)  # SQL runs here, not in the model
                outputs.append(FunctionCallOutput(type="function_call_output", call_id=call.call_id, output=result))
            response = self.openai.responses.create(conversation=conversation_id, input=outputs, extra_body=ref)

        return {
            "answer": response.output_text or "Sorry, I couldn't find an answer.",
            "conversation_id": conversation_id,
            "tools": tools_used,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
