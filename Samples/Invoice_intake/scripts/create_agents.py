"""Publishes the two prompt agents used by the web app to the Foundry project.

    python scripts/create_agents.py

Each run creates a new agent version (older versions stay visible in the Foundry portal).
Definitions live in src/app/agent_definitions.py.
"""
from __future__ import annotations

import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FunctionTool,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    Reasoning,
    TextResponseFormatJsonSchema,
)
from azure.identity import DefaultAzureCredential

import common as c

sys.path.insert(0, str(c.ROOT / "src"))
from app.agent_definitions import (  # noqa: E402
    REVIEW_AGENT_INSTRUCTIONS,
    REVIEW_OUTPUT_SCHEMA,
    SALES_AGENT_INSTRUCTIONS,
    SALES_TOOLS,
)


def main() -> None:
    c.load_env()
    c.step("Foundry agents")
    project = AIProjectClient(endpoint=c.env("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())
    model = c.env("CHAT_DEPLOYMENT_NAME")
    review_name = c.env("REVIEW_AGENT_NAME", "invoice-review-agent")
    sales_name = c.env("SALES_AGENT_NAME", "sales-analyst")
    # Reasoning models (gpt-5 family, o-series) answer faster on stage with low reasoning effort.
    extra = {"reasoning": Reasoning(effort="low")} if model.startswith(("gpt-5", "o")) else {}

    review = project.agents.create_version(
        agent_name=review_name,
        description="Second opinion on supplier invoices; detects prompt injection and manual alterations.",
        definition=PromptAgentDefinition(
            model=model,
            instructions=REVIEW_AGENT_INSTRUCTIONS,
            text=PromptAgentDefinitionTextOptions(
                format=TextResponseFormatJsonSchema(name="invoice_review", schema=REVIEW_OUTPUT_SCHEMA, strict=True)),
            **extra,
        ),
    )
    c.ok(f"{review.name} version {review.version} ({model})")

    tools = [FunctionTool(name=t["name"], description=t["description"], parameters=t["parameters"], strict=True)
             for t in SALES_TOOLS]
    sales = project.agents.create_version(
        agent_name=sales_name,
        description="Answers audience questions about sales, margin and supplier prices with SQL-backed tools.",
        definition=PromptAgentDefinition(
            model=model,
            instructions=SALES_AGENT_INSTRUCTIONS,
            tools=tools,
            **extra,
        ),
    )
    c.ok(f"{sales.name} version {sales.version} ({len(tools)} function tools)")


if __name__ == "__main__":
    main()
