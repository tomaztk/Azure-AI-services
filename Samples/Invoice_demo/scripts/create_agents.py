"""Publishes the data agent used by the web app to the Foundry project.

    python scripts/create_agents.py

Each run creates a new agent version (older versions stay visible in the Foundry portal).
The definition lives in src/app/agent_definitions.py, the tool code in src/app/data_tools.py.
"""
from __future__ import annotations

import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition, Reasoning
from azure.identity import DefaultAzureCredential

import common as c

sys.path.insert(0, str(c.ROOT / "src"))
from app.agent_definitions import AGENT_INSTRUCTIONS, TOOLS  # noqa: E402


def main() -> None:
    c.load_env()
    c.step("Foundry data agent")
    project = AIProjectClient(endpoint=c.env("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    model = c.env("CHAT_DEPLOYMENT_NAME")
    name = c.env("AGENT_NAME", "invoice-data-agent")
    # Reasoning models (gpt-5 family, o-series) answer faster on stage with low reasoning effort.
    extra = {"reasoning": Reasoning(effort="low")} if model.startswith(("gpt-5", "o")) else {}

    tools = [FunctionTool(name=t["name"], description=t["description"], parameters=t["parameters"], strict=True)
             for t in TOOLS]
    agent = project.agents.create_version(
        agent_name=name,
        description="Answers questions about processed invoices, supplier prices and sales with SQL-backed tools.",
        definition=PromptAgentDefinition(model=model, instructions=AGENT_INSTRUCTIONS, tools=tools, **extra),
    )
    c.ok(f"{agent.name} version {agent.version} ({model}, {len(tools)} function tools)")


if __name__ == "__main__":
    main()
