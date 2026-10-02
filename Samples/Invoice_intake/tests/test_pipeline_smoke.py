"""End-to-end smoke test of the pipeline and API with fake Azure services (no cloud needed)."""
from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import db, main, pipeline as pl
from app.rules import ReviewOpinion

CU_RESULT = {"contents": [{"markdown": "INVOICE Brennerwerk ...", "fields": {
    "InvoiceId": {"valueString": "BW-260927-01", "confidence": 0.97},
    "VendorName": {"valueString": "Brennerwerk Metall GmbH", "confidence": 0.95},
    "PONumber": {"valueString": "PO-DEMO-1001", "confidence": 0.94},
    "InvoiceDate": {"valueDate": date.today().isoformat()},
    "SubtotalAmount": {"valueObject": {"Amount": {"valueNumber": 2268.0}}},
    "TotalTaxAmount": {"valueObject": {"Amount": {"valueNumber": 453.6}}},
    "TotalAmount": {"valueObject": {"Amount": {"valueNumber": 2721.6, "confidence": 0.93},
                                    "CurrencyCode": {"valueString": "EUR"}}},
    "LineItems": {"valueArray": [{"valueObject": {
        "Description": {"valueString": "Trail Frame Alu 29in"}, "ProductCode": {"valueString": "AR-FRM-100"},
        "Quantity": {"valueNumber": 12}, "UnitPrice": {"valueObject": {"Amount": {"valueNumber": 189.0}}},
        "TotalAmount": {"valueObject": {"Amount": {"valueNumber": 2268.0}}}}}]},
}}]}

REF = {
    "vendors": [{"VendorId": 1, "VendorCode": "V001", "VendorName": "Brennerwerk Metall GmbH", "VatId": "ATU99100001",
                 "Iban": "AT61", "CountryCode": "AT"}],
    "products": [{"ProductId": 1, "Sku": "AR-FRM-100", "ProductName": "Trail Frame Alu 29in", "VendorId": 1,
                  "ContractPrice": Decimal("189.00"), "MaxPriceDeviationPct": Decimal("2.00")}],
    "po": {"PurchaseOrderId": 7, "PONumber": "PO-DEMO-1001", "VendorId": 1, "OrderDate": date.today(),
           "lines": [{"LineNumber": 1, "ProductId": 1, "Quantity": Decimal(12), "UnitPrice": Decimal("189.00"),
                      "ReceivedQuantity": Decimal(12)}]},
}


class FakeCU:
    async def analyze(self, data, content_type, analyzer_id="prebuilt-invoice"):
        return CU_RESULT


class FakeAgents:
    def __init__(self, opinion):
        self.opinion = opinion
        self.seen_document = None

    def review_invoice(self, ctx, document_text):
        self.seen_document = document_text
        return self.opinion

    def ask(self, question, persona, conversation_id=None):
        return {"answer": f"**{persona}**: 42", "conversation_id": "conv_1", "tools": ["get_sales_summary"],
                "duration_ms": 5}


class FakeStore:
    def save_upload(self, *a):
        return "invoices/audience/x.jpg"

    def save_extraction(self, *a):
        pass

    def read(self, path):
        return b"%PDF-1.4"


@pytest.fixture
def fake_db(monkeypatch):
    saved = {}
    monkeypatch.setattr(db, "set_stage", lambda *a, **k: None)
    monkeypatch.setattr(db, "load_reference_data", lambda *a: REF)
    monkeypatch.setattr(db, "find_duplicates", lambda *a: [])
    monkeypatch.setattr(db, "save_result", lambda iid, header, lines, *a: saved.update(header=header, lines=lines, log=a))
    monkeypatch.setattr(db, "mark_failed", lambda iid, reason, ms=None: saved.update(failed=reason))
    monkeypatch.setattr(db, "create_invoice", lambda *a: 123)
    monkeypatch.setattr(db, "log_question", lambda *a: None)
    return saved


def run_pipeline(opinion):
    agents = FakeAgents(opinion)
    p = pl.InvoicePipeline(FakeCU(), agents, FakeStore())
    asyncio.run(p.process(1, b"\xff\xd8\xff...", "image/jpeg", "audience", "session12345"))
    return agents


def test_pipeline_auto_approves_clean_invoice(fake_db):
    agents = run_pipeline(ReviewOpinion(recommendation="approve", summary="Looks fine."))
    header = fake_db["header"]
    assert header["Status"] == "AutoApproved", header["DecisionReason"]
    assert header["VendorId"] == 1 and header["PurchaseOrderId"] == 7
    assert fake_db["lines"][0]["ContractUnitPrice"] == Decimal("189.00")
    assert fake_db["log"][0] == "AutoApproved"
    assert agents.seen_document.startswith("INVOICE")


def test_pipeline_routes_injection_to_human(fake_db):
    run_pipeline(ReviewOpinion(recommendation="review", summary="Asks the AI to approve.", injection_detected=True))
    assert fake_db["header"]["Status"] == "NeedsReview"
    assert fake_db["header"]["InjectionDetected"] is True


def test_api_upload_and_ask(fake_db, monkeypatch):
    monkeypatch.setitem(main.services, "pipeline", pl.InvoicePipeline(FakeCU(), FakeAgents(ReviewOpinion("approve")), FakeStore()))
    monkeypatch.setitem(main.services, "agents", FakeAgents(ReviewOpinion("approve")))
    client = TestClient(main.app)  # no context manager: skips the Azure clients in lifespan

    assert client.get("/api/health").json() == {"status": "ok"}
    assert "Invoice desk" in client.get("/").text

    r = client.post("/api/invoices", data={"session_id": "session12345", "source": "audience"},
                    files={"file": ("x.jpg", b"\xff\xd8\xff\xe0 jpeg bytes", "image/jpeg")})
    assert r.status_code == 200 and r.json() == {"invoice_id": 123}

    r = client.post("/api/invoices", data={"session_id": "session12345", "source": "audience"},
                    files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415

    r = client.post("/api/invoices", data={"session_id": "session12345", "source": "stage"},
                    files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 401  # stage uploads need the presenter key

    r = client.post("/api/ask", json={"question": "Top products?", "persona": "dach_sales", "session_id": "session12345"})
    assert r.status_code == 200 and "dach_sales" in r.json()["answer"]

    assert client.get("/api/feed").status_code in (401, 403)
