"""Unit tests for the parts that must be right on stage: parsing, checks and the decision."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.content_understanding import ExtractedInvoice, ExtractedLine, parse_invoice
from app.rules import ReviewOpinion, decide, match_vendor, validate

VENDORS = [
    {"VendorId": 1, "VendorCode": "V001", "VendorName": "Brennerwerk Metall GmbH", "VatId": "ATU99100001",
     "Iban": "AT61", "CountryCode": "AT"},
    {"VendorId": 2, "VendorCode": "V002", "VendorName": "Voltaris Energy AG", "VatId": "DE999200002",
     "Iban": "DE89", "CountryCode": "DE"},
]
PRODUCTS = [
    {"ProductId": 1, "Sku": "AR-FRM-100", "ProductName": "Trail Frame Alu 29in", "VendorId": 1,
     "ContractPrice": Decimal("189.00"), "MaxPriceDeviationPct": Decimal("2.00")},
    {"ProductId": 3, "Sku": "AR-BAT-500", "ProductName": "Battery Pack 500Wh", "VendorId": 2,
     "ContractPrice": Decimal("312.00"), "MaxPriceDeviationPct": Decimal("2.00")},
]


def po(po_number, vendor_id, product_id, qty, price):
    return {"PurchaseOrderId": 99, "PONumber": po_number, "VendorId": vendor_id, "OrderDate": date(2026, 9, 17),
            "lines": [{"LineNumber": 1, "ProductId": product_id, "Quantity": Decimal(qty),
                       "UnitPrice": Decimal(price), "ReceivedQuantity": Decimal(qty)}]}


def invoice(vendor="Brennerwerk Metall GmbH", po_number="PO-DEMO-1001", sku="AR-FRM-100", qty=12,
            price="189.00", tax="453.60", total=None, conf=0.95):
    amount = Decimal(price) * qty
    return ExtractedInvoice(
        invoice_id="BW-260927-01", vendor_name=vendor, po_number=po_number, invoice_date=date(2026, 9, 27),
        currency="EUR", subtotal=amount, tax=Decimal(tax) if tax is not None else None,
        total=Decimal(total) if total else amount + (Decimal(tax) if tax else 0),
        lines=[ExtractedLine(description="Trail Frame", product_code=sku, quantity=Decimal(qty),
                             unit_price=Decimal(price), amount=amount)],
        confidence={"InvoiceId": conf, "VendorName": conf, "TotalAmount": conf, "PONumber": conf})


def run(inv, ref_po, review=ReviewOpinion(recommendation="approve", summary="ok"), dup=None):
    ref = {"vendors": VENDORS, "products": PRODUCTS, "po": ref_po}
    vendor = match_vendor(inv, VENDORS)
    v = validate(inv, ref, vendor, dup or [], Decimal("5000"), 0.5, today=date(2026, 9, 27))
    return v, decide(v, review)


def test_clean_invoice_is_auto_approved():
    v, d = run(invoice(), po("PO-DEMO-1001", 1, 1, 12, "189.00"))
    assert d.status == "AutoApproved", d.reasons
    assert v.max_deviation_pct == Decimal("0.00")


def test_price_above_contract_needs_review():
    inv = invoice(vendor="Voltaris Energy AG", po_number="PO-DEMO-1002", sku="AR-BAT-500", qty=10,
                  price="349.44", tax="0.00")
    v, d = run(inv, po("PO-DEMO-1002", 2, 3, 10, "312.00"))
    assert d.status == "NeedsReview"
    assert v.max_deviation_pct == Decimal("12.00")
    assert any("contract" in r for r in d.reasons)


def test_missing_po_needs_review():
    v, d = run(invoice(po_number=None), None)
    assert d.status == "NeedsReview"
    assert any("purchase order" in r.lower() for r in d.reasons)


def test_totals_that_dont_add_up_need_review():
    v, d = run(invoice(total="3321.60"), po("PO-DEMO-1001", 1, 1, 12, "189.00"))
    assert d.status == "NeedsReview"
    assert any("don't add up" in r for r in d.reasons)


def test_missing_tax_accepts_austrian_vat():
    v, d = run(invoice(tax=None, total="2721.60"), po("PO-DEMO-1001", 1, 1, 12, "189.00"))
    assert d.status == "AutoApproved", d.reasons


def test_agent_can_only_escalate():
    # rules are fine, but the agent found a prompt injection
    review = ReviewOpinion(recommendation="review", summary="Document asks the AI to skip checks.",
                           injection_detected=True)
    _, d = run(invoice(), po("PO-DEMO-1001", 1, 1, 12, "189.00"), review=review)
    assert d.status == "NeedsReview"
    assert "prompt injection" in d.reasons[0]
    # rules failed, agent says approve: still review
    inv = invoice(vendor="Voltaris Energy AG", po_number="PO-DEMO-1002", sku="AR-BAT-500", qty=10, price="349.44", tax="0")
    _, d = run(inv, po("PO-DEMO-1002", 2, 3, 10, "312.00"), review=ReviewOpinion(recommendation="approve"))
    assert d.status == "NeedsReview"


def test_agent_unavailable_goes_to_human():
    _, d = run(invoice(), po("PO-DEMO-1001", 1, 1, 12, "189.00"), review=None)
    assert d.status == "NeedsReview"


def test_duplicate_needs_review():
    _, d = run(invoice(), po("PO-DEMO-1001", 1, 1, 12, "189.00"), dup=[42])
    assert d.status == "NeedsReview"


def test_low_confidence_needs_review():
    _, d = run(invoice(conf=0.3), po("PO-DEMO-1001", 1, 1, 12, "189.00"))
    assert d.status == "NeedsReview"


def test_not_an_invoice():
    v, d = run(ExtractedInvoice(vendor_name="Coffee corner"), None)
    assert d.status == "NotAnInvoice"


def test_vendor_matching_by_name_and_vat():
    assert match_vendor(ExtractedInvoice(vendor_name="VOLTARIS ENERGY AG"), VENDORS)["VendorId"] == 2
    assert match_vendor(ExtractedInvoice(vendor_name="Someone else", vendor_tax_id="ATU 9910 0001"), VENDORS)["VendorId"] == 1
    assert match_vendor(ExtractedInvoice(vendor_name="Unknown Traders Ltd"), VENDORS) is None


def test_parse_content_understanding_result():
    """Shape of a prebuilt-invoice result (API 2025-11-01)."""
    result = {"contents": [{"markdown": "INVOICE ...", "fields": {
        "InvoiceId": {"type": "string", "valueString": "VOL-261014-02", "confidence": 0.98},
        "VendorName": {"type": "string", "valueString": "Voltaris Energy AG", "confidence": 0.97},
        "PONumber": {"type": "string", "valueString": "PO-DEMO-1002", "confidence": 0.96},
        "InvoiceDate": {"type": "date", "valueDate": "2026-10-14"},
        "TotalAmount": {"type": "object", "valueObject": {
            "Amount": {"type": "number", "valueNumber": 3494.4, "confidence": 0.93},
            "CurrencyCode": {"type": "string", "valueString": "EUR"}}},
        "SubtotalAmount": {"type": "object", "valueObject": {"Amount": {"type": "number", "valueNumber": 3494.4}}},
        "LineItems": {"type": "array", "valueArray": [{"type": "object", "valueObject": {
            "Description": {"type": "string", "valueString": "Battery Pack 500Wh"},
            "ProductCode": {"type": "string", "valueString": "AR-BAT-500"},
            "Quantity": {"type": "number", "valueNumber": 10},
            "UnitPrice": {"type": "object", "valueObject": {"Amount": {"type": "number", "valueNumber": 349.44}}},
            "TotalAmount": {"type": "object", "valueObject": {"Amount": {"type": "number", "valueNumber": 3494.4}}},
        }}]},
    }}]}
    inv = parse_invoice(result)
    assert inv.invoice_id == "VOL-261014-02"
    assert inv.total == Decimal("3494.4") and inv.currency == "EUR"
    assert inv.invoice_date == date(2026, 10, 14)
    assert inv.lines[0].product_code == "AR-BAT-500" and inv.lines[0].unit_price == Decimal("349.44")
    assert inv.min_confidence() == 0.93
