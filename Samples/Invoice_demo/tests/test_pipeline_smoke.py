"""End-to-end smoke test of the pipeline and API with fake Azure services (no cloud needed)."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import data_tools, db, main, pipeline as pl

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
    def __init__(self, result=CU_RESULT):
        self.result = result

    async def analyze(self, data, content_type, analyzer_id="prebuilt-invoice"):
        return self.result


class FakeAgents:
    def ask(self, question, conversation_id=None):
        return {"answer": "29 invoices were auto-approved.", "conversation_id": "conv_1",
                "tools": ["get_invoice_processing_stats"], "duration_ms": 5}


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


def run_pipeline(cu=None):
    p = pl.InvoicePipeline(cu or FakeCU(), FakeStore())
    asyncio.run(p.process(1, b"\xff\xd8\xff...", "image/jpeg", "audience", "session12345"))


def test_pipeline_auto_approves_clean_invoice(fake_db):
    run_pipeline()
    header = fake_db["header"]
    assert header["Status"] == "AutoApproved", header["DecisionReason"]
    assert header["VendorId"] == 1 and header["PurchaseOrderId"] == 7
    assert fake_db["lines"][0]["ContractUnitPrice"] == Decimal("189.00")
    assert fake_db["log"][0] == "AutoApproved"


def test_pipeline_routes_price_deviation_to_a_person(fake_db):
    result = json.loads(json.dumps(CU_RESULT))
    item = result["contents"][0]["fields"]["LineItems"]["valueArray"][0]["valueObject"]
    item["UnitPrice"]["valueObject"]["Amount"]["valueNumber"] = 211.68  # +12 %
    item["TotalAmount"]["valueObject"]["Amount"]["valueNumber"] = 2540.16
    fields = result["contents"][0]["fields"]
    fields["SubtotalAmount"]["valueObject"]["Amount"]["valueNumber"] = 2540.16
    fields["TotalTaxAmount"]["valueObject"]["Amount"]["valueNumber"] = 508.03
    fields["TotalAmount"]["valueObject"]["Amount"]["valueNumber"] = 3048.19
    run_pipeline(FakeCU(result))
    assert fake_db["header"]["Status"] == "NeedsReview"
    assert "contract" in fake_db["header"]["DecisionReason"]


def test_tool_execution_returns_json(monkeypatch):
    monkeypatch.setattr(db, "query", lambda sql, params=(): [{"status": "AutoApproved", "invoices": 3,
                                                               "avg_processing_seconds": Decimal("12.5"),
                                                               "total_amount": Decimal("100.00")}])
    out = json.loads(data_tools.execute("get_invoice_processing_stats", '{"since_minutes": 30, "source": "audience"}'))
    assert out["invoices"] == 3 and out["auto_approval_rate_pct"] == 100.0
    assert "error" in json.loads(data_tools.execute("drop_tables", "{}"))


def test_api_upload_and_ask(fake_db, monkeypatch):
    monkeypatch.setitem(main.services, "pipeline", pl.InvoicePipeline(FakeCU(), FakeStore()))
    monkeypatch.setitem(main.services, "agents", FakeAgents())
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

    r = client.post("/api/ask", json={"question": "How many were approved?", "session_id": "session12345"})
    assert r.status_code == 200 and "auto-approved" in r.json()["answer"]

    assert client.get("/api/feed").status_code in (401, 403)
