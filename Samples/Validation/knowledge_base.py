"""
knowledge_base.py
-----------------
Simulates an enterprise knowledge base that the validation agent queries to
fact-check extracted information.

In production this would be backed by Azure AI Search, a SQL database,
SharePoint, or any other enterprise data source connected via MCP or a
FunctionTool.  For the demo we use a local JSON structure.
"""

from __future__ import annotations
import json
from typing import Any

# ── Simulated enterprise KB ──────────────────────────────────────────────────
_KB: dict[str, Any] = {

    # ── Valid product taxonomy ────────────────────────────────────────────────
    "product_taxonomy": {
        "Banking": {
            "Credit Card": ["Payment Dispute", "Limit Increase", "Fraud Report", "Card Replacement", "Interest Query"],
            "Savings Account": ["Balance Inquiry", "Transfer", "Interest Rate Query", "Account Closure"],
            "Mortgage": ["Rate Inquiry", "Payment Issue", "Refinance", "Early Repayment"],
            "Loans": ["Personal Loan", "Car Loan", "Application Status", "Repayment"],
        },
        "Telecom": {
            "Broadband": ["Speed Issue", "Outage Report", "Upgrade", "Sales Inquiry", "Billing"],
            "Mobile": ["Roaming", "Plan Change", "Tech Support", "SIM Issue", "Billing"],
            "TV": ["Channel Query", "Equipment Fault", "Upgrade", "Cancellation"],
        },
        "Insurance": {
            "Motor": ["New Policy", "Claim", "Renewal", "NCB Query", "Policy Change"],
            "Home": ["New Policy", "Claim", "Renewal", "Coverage Query"],
            "Life": ["Policy Query", "Beneficiary Change", "Premium Query", "Claim"],
        },
        "Utilities": {
            "Electricity": ["Billing", "Outage Report", "Meter Reading", "Tariff Change"],
            "Gas": ["Billing", "Safety Issue", "Meter Reading", "Tariff Change"],
            "Water": ["Billing", "Leak Report", "Meter Reading"],
        },
    },

    # ── Valid sentiment labels ────────────────────────────────────────────────
    "valid_sentiments": ["Positive", "Negative", "Neutral", "Mixed"],

    # ── Valid tonality labels ─────────────────────────────────────────────────
    "valid_tonalities": [
        "Formal", "Informal", "Empathetic", "Tense",
        "Neutral", "Confrontational", "Friendly", "Professional",
    ],

    # ── Valid resolution statuses ─────────────────────────────────────────────
    "valid_resolutions": ["Resolved", "Unresolved", "Escalated", "Pending"],

    # ── Known service labels (non-exhaustive; used for fuzzy matching) ────────
    "known_services": [
        "Billing Dispute", "Technical Support", "Account Inquiry",
        "Sales Inquiry", "Complaint", "General Inquiry",
        "Fraud Report", "Cancellation", "New Policy",
        "Claim", "Upgrade", "Order Management", "Callback Request",
    ],

    # ── Business policy rules (checked separately by rules_engine.py) ────────
    "policies": {
        "summary_min_words": 15,
        "summary_max_words": 120,
        "sentiment_score_range": (-1.0, 1.0),
        "required_fields": [
            "audio_file", "summary", "product_L1", "product_L2",
            "customer_sentiment", "agent_sentiment", "tonality",
            "service", "resolution",
        ],
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def lookup_product_taxonomy(l1: str, l2: str, l3: str) -> dict:
    """
    Check whether (L1 → L2 → L3) is a known taxonomy path.
    Returns a dict with keys: valid_l1, valid_l2, valid_l3, suggestions.
    """
    taxonomy = _KB["product_taxonomy"]
    valid_l1 = l1 in taxonomy
    valid_l2 = valid_l1 and l2 in taxonomy.get(l1, {})
    valid_l3 = valid_l2 and l3 in taxonomy.get(l1, {}).get(l2, [])

    suggestions = {}
    if not valid_l1:
        suggestions["L1"] = list(taxonomy.keys())
    elif not valid_l2:
        suggestions["L2"] = list(taxonomy[l1].keys())
    elif not valid_l3:
        suggestions["L3"] = taxonomy[l1][l2]

    return {
        "valid_l1": valid_l1,
        "valid_l2": valid_l2,
        "valid_l3": valid_l3,
        "full_path_valid": valid_l1 and valid_l2 and valid_l3,
        "suggestions": suggestions,
    }


def lookup_sentiment(label: str) -> bool:
    return label in _KB["valid_sentiments"]


def lookup_tonality(label: str) -> bool:
    return label in _KB["valid_tonalities"]


def lookup_resolution(label: str) -> bool:
    return label in _KB["valid_resolutions"]


def lookup_service(service: str) -> dict:
    """Fuzzy match service against known services."""
    known = _KB["known_services"]
    exact = service in known
    close = [k for k in known if service.lower() in k.lower() or k.lower() in service.lower()]
    return {"exact_match": exact, "close_matches": close}


def get_policies() -> dict:
    return _KB["policies"]


def kb_as_json() -> str:
    """Return the full KB as a JSON string (used as agent context)."""
    return json.dumps(_KB, indent=2)
