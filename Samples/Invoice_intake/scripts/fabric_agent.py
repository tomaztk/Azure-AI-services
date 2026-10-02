"""Foundry agent grounded on Fabric IQ: "Ask your sales data" through the Fabric data agent / ontology.

Run this AFTER docs/FABRIC_SETUP.md (mirroring, semantic model, ontology, data agent).

    # connect the Foundry project to the published Fabric data agent (paste its browser URL)
    python scripts/fabric_agent.py connect --data-agent-url "https://app.fabric.microsoft.com/groups/<ws>/aiskills/<id>?..."

    # create (or update) the agent, using the Fabric data agent connection
    python scripts/fabric_agent.py create --connection alpenrad-fabric

    # or use the Fabric IQ (OneLake catalog) tool connection instead
    python scripts/fabric_agent.py create --connection <connection-name> --tool fabric-iq

    # ask one question, or start an interactive chat
    python scripts/fabric_agent.py ask "Why did gross margin on the 500Wh battery pack drop?"
    python scripts/fabric_agent.py chat

The Fabric tools use identity passthrough (On-Behalf-Of): queries run as YOU (az login),
so Fabric permissions and Power BI row-level security apply. Service principals and the
web app's managed identity can't call them; that's why the audience web page uses its own
SQL-backed tools and this agent runs in the Foundry playground, in Teams, or here.
"""
from __future__ import annotations

import argparse
import re
import time

import httpx
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FabricDataAgentToolParameters,
    FabricIQPreviewTool,
    MicrosoftFabricPreviewTool,
    PromptAgentDefinition,
    ToolProjectConnection,
)
from azure.identity import DefaultAzureCredential

import common as c

AGENT_NAME = "fabric-sales-analyst"

INSTRUCTIONS = """\
You are the sales and procurement analyst of Alpenrad Handels GmbH, a fictional e-bike parts wholesaler in Vienna.
For every question about sales, revenue, gross margin, customers, regions, products, suppliers, purchase prices,
contracts or supplier invoices, use the Fabric tool. Never invent numbers.

Business vocabulary:
- Revenue = SalesOrderLines.NetAmount. Purchase cost = SalesOrderLines.CostAmount. Gross margin = revenue - cost.
- Approved supplier invoices have Status 'AutoApproved' (by the AI intake) or 'Approved' (by a person).
  Source 'legacy' = old manual process; 'stage', 'audience', 'cli' = the new AI intake.
- Price deviation = invoice unit price vs contract price (InvoiceLines.PriceDeviationPct).
- Regions: DACH, Nordics, Benelux, Italy, UK & Ireland.

Answer in 2-5 sentences or a small table. When a number is surprising (a margin drop, a supplier invoicing above
contract), explain the likely cause with the data. Format money as EUR.
"""


def connect(args: argparse.Namespace) -> None:
    """Create the Foundry project connection to a published Fabric data agent (ARM REST call)."""
    c.load_env()
    workspace_id, artifact_id = args.workspace_id, args.artifact_id
    if args.data_agent_url:
        m = re.search(r"/groups/([0-9a-fA-F-]{36})/aiskills/([0-9a-fA-F-]{36})", args.data_agent_url)
        if not m:
            raise SystemExit("Could not find .../groups/<workspace_id>/aiskills/<artifact_id> in the URL.")
        workspace_id, artifact_id = m.group(1), m.group(2)
    if not (workspace_id and artifact_id):
        raise SystemExit("Pass --data-agent-url, or --workspace-id and --artifact-id.")
    sub, rg = c.env("AZURE_SUBSCRIPTION_ID"), c.env("AZURE_RESOURCE_GROUP")
    account, project = c.env("FOUNDRY_ACCOUNT_NAME"), c.env("FOUNDRY_PROJECT_NAME")
    url = (f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/"
           f"Microsoft.CognitiveServices/accounts/{account}/projects/{project}/connections/{args.name}")
    token = DefaultAzureCredential().get_token("https://management.azure.com/.default").token
    body = {"properties": {"category": "CustomKeys", "authType": "CustomKeys",
                           "credentials": {"keys": {"workspace_id": workspace_id, "artifact_id": artifact_id}}}}
    resp = httpx.put(url, params={"api-version": "2025-04-01-preview"}, json=body,
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code >= 400:
        raise SystemExit(f"{resp.status_code}: {resp.text}")
    c.ok(f"Connection '{args.name}' created: {resp.json().get('id')}")
    c.ok(f"Next: python scripts/fabric_agent.py create --connection {args.name}")


def project_client() -> AIProjectClient:
    c.load_env()
    return AIProjectClient(endpoint=c.env("FOUNDRY_PROJECT_ENDPOINT"), credential=DefaultAzureCredential())


def create(args: argparse.Namespace) -> None:
    project = project_client()
    connection = project.connections.get(args.connection)
    if args.tool == "fabric-iq":
        tool = FabricIQPreviewTool(project_connection_id=connection.id, require_approval="never")
    else:
        tool = MicrosoftFabricPreviewTool(fabric_dataagent_preview=FabricDataAgentToolParameters(
            project_connections=[ToolProjectConnection(project_connection_id=connection.id)]))
    agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        description="Sales and procurement analyst grounded on Fabric IQ (mirrored Azure SQL data).",
        definition=PromptAgentDefinition(model=args.model or c.env("CHAT_DEPLOYMENT_NAME"),
                                         instructions=INSTRUCTIONS, tools=[tool]),
    )
    c.ok(f"{agent.name} version {agent.version} created with the {args.tool} tool ({connection.name})")
    c.ok("Try it in the Foundry portal playground, or: python scripts/fabric_agent.py chat")


def _ask(openai, conversation_id: str, question: str, background: bool) -> str:
    kwargs = {"conversation": conversation_id, "input": question,
              "extra_body": {"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}}}
    if background:
        # Fabric data agent queries can take longer than a normal tool-call timeout.
        response = openai.responses.create(background=True, **kwargs)
        while response.status in ("queued", "in_progress"):
            time.sleep(2)
            response = openai.responses.retrieve(response.id)
        if response.status != "completed":
            return f"[{response.status}] {getattr(response, 'error', '')}"
        return response.output_text
    return openai.responses.create(**kwargs).output_text


def ask(args: argparse.Namespace) -> None:
    openai = project_client().get_openai_client()
    conversation = openai.conversations.create()
    started = time.monotonic()
    print(_ask(openai, conversation.id, args.question, args.background))
    print(f"\n({time.monotonic() - started:.1f} s)")


def chat(args: argparse.Namespace) -> None:
    openai = project_client().get_openai_client()
    conversation = openai.conversations.create()
    print("Ask about sales, margin, suppliers or invoices. Empty line to quit.\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        started = time.monotonic()
        print(f"\nagent> {_ask(openai, conversation.id, q, args.background)}  ({time.monotonic() - started:.1f} s)\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("connect", help="create the Foundry connection to a published Fabric data agent")
    p.add_argument("--data-agent-url", help="browser URL of the data agent (.../groups/<ws>/aiskills/<id>...)")
    p.add_argument("--workspace-id")
    p.add_argument("--artifact-id")
    p.add_argument("--name", default="alpenrad-fabric", help="connection name")
    p.set_defaults(fn=connect)
    p = sub.add_parser("create", help="create or update the Fabric-grounded agent")
    p.add_argument("--connection", required=True, help="name of the Fabric connection in the Foundry project")
    p.add_argument("--tool", choices=["data-agent", "fabric-iq"], default="data-agent")
    p.add_argument("--model", help="model deployment (default: CHAT_DEPLOYMENT_NAME)")
    p.set_defaults(fn=create)
    p = sub.add_parser("ask", help="ask one question")
    p.add_argument("question")
    p.add_argument("--background", action="store_true", help="use background mode for long Fabric queries")
    p.set_defaults(fn=ask)
    p = sub.add_parser("chat", help="interactive chat")
    p.add_argument("--background", action="store_true")
    p.set_defaults(fn=chat)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
