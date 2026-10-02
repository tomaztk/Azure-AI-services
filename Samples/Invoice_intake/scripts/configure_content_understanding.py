"""Tells Content Understanding which model deployments to use (one-time, per Foundry resource).

Prebuilt analyzers such as prebuilt-invoice refer to model aliases; this maps the aliases
to the deployments created by the Bicep template.
"""
from __future__ import annotations

import json

import httpx
from azure.identity import DefaultAzureCredential

import common as c

API_VERSION = "2025-11-01"


def main() -> None:
    c.load_env()
    c.step("Content Understanding model defaults")
    endpoint = c.env("FOUNDRY_ACCOUNT_ENDPOINT").rstrip("/")
    chat_model = c.env("CHAT_MODEL_NAME")
    chat = c.env("CHAT_DEPLOYMENT_NAME")
    mini_model = c.env("MINI_MODEL_NAME")
    mini = c.env("MINI_DEPLOYMENT_NAME")
    emb_model = c.env("EMBEDDING_MODEL_NAME")
    emb = c.env("EMBEDDING_DEPLOYMENT_NAME")

    body = {
        "modelDeployments": {
            chat_model: chat,
            mini_model: mini,
            emb_model: emb,
            "prebuilt-analyzer-completion": chat,
            "prebuilt-analyzer-completion-mini": mini,
            "prebuilt-analyzer-embedding": emb,
        }
    }
    token = DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default").token
    resp = httpx.patch(
        f"{endpoint}/contentunderstanding/defaults",
        params={"api-version": API_VERSION},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/merge-patch+json"},
        content=json.dumps(body),
        timeout=60,
    )
    if resp.status_code >= 400:
        # Some gateways only accept application/json for this call.
        resp = httpx.patch(
            f"{endpoint}/contentunderstanding/defaults",
            params={"api-version": API_VERSION},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            content=json.dumps(body),
            timeout=60,
        )
    if resp.status_code >= 400:
        c.fail(f"{resp.status_code}: {resp.text}")
        c.warn("If this is a 401/403, role assignments can take a few minutes to apply. Run this script again:")
        c.warn("  python scripts/configure_content_understanding.py")
        raise SystemExit(1)
    c.ok(f"prebuilt analyzers use '{chat}', '{mini}' and '{emb}'")

    check = httpx.get(f"{endpoint}/contentunderstanding/analyzers/prebuilt-invoice",
                      params={"api-version": API_VERSION},
                      headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if check.status_code == 200:
        supported = check.json().get("supportedModels", {}).get("completion", [])
        if supported and chat_model not in supported:
            c.warn(f"prebuilt-invoice lists {supported} as supported completion models; "
                   f"'{chat_model}' is not among them. Consider changing CHAT_MODEL_NAME.")
        else:
            c.ok("prebuilt-invoice analyzer is ready")


if __name__ == "__main__":
    main()
