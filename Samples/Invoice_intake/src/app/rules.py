"""Deterministic invoice checks and the approval decision.

Design rule for the demo: the rules decide, the AI can only escalate.
  - Every rule that fails sends the invoice to a human.
  - The review agent (an LLM) can add reasons to send it to a human, but it can never
    approve an invoice that a rule flagged. A prompt injection in a document therefore
    can't talk its way into an approval.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .content_understanding import ExtractedInvoice

LEGAL_SUFFIXES = r"\b(gmbh|ag|s\.?r\.?l\.?|srl|ab|ltd|limited|inc|co|kg|oy|bv|nv|sa|spa|s\.?p\.?a\.?)\b"
TOLERANCE_ABS = Decimal("1.00")
TOLERANCE_REL = Decimal("0.005")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class MatchedLine:
    description: str | None
    sku: str | None
    product_id: int | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    contract_price: Decimal | None = None
    deviation_pct: Decimal | None = None
    max_deviation_pct: Decimal | None = None
    po_quantity: Decimal | None = None
    received_quantity: Decimal | None = None

    def as_db_row(self) -> dict[str, Any]:
        return {"ProductId": self.product_id, "Sku": (self.sku or "")[:40] or None, "Description": self.description,
                "Quantity": _fit(self.quantity, 10), "UnitPrice": _fit(self.unit_price, 10),
                "LineAmount": _fit(self.amount, 12), "ContractUnitPrice": _fit(self.contract_price, 10),
                "PriceDeviationPct": _fit(self.deviation_pct, 5)}


def _fit(value: Decimal | None, integer_digits: int) -> Decimal | None:
    """Round to cents and drop values that don't fit the SQL decimal column (garbage from a bad scan)."""
    if value is None or abs(value) >= Decimal(10) ** integer_digits:
        return None
    return value.quantize(Decimal("0.01"))


@dataclass
class Validation:
    is_invoice: bool
    vendor: dict[str, Any] | None
    po: dict[str, Any] | None
    lines: list[MatchedLine]
    checks: list[Check] = field(default_factory=list)
    max_deviation_pct: Decimal | None = None
    min_confidence: float | None = None

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]


@dataclass
class ReviewOpinion:
    """What the review agent returned (parsed from its JSON output)."""
    recommendation: str = "review"
    summary: str = ""
    concerns: list[str] = field(default_factory=list)
    injection_detected: bool = False
    manual_alteration_detected: bool = False
    not_an_invoice: bool = False


@dataclass
class Decision:
    status: str               # AutoApproved | NeedsReview | NotAnInvoice
    reasons: list[str]
    log_action: str

    @property
    def reason_text(self) -> str:
        return " | ".join(self.reasons) if self.reasons else "All checks passed."


# ------------------------------------------------------------------ helpers
def normalize_code(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def normalize_name(value: str | None) -> str:
    v = (value or "").lower()
    v = re.sub(LEGAL_SUFFIXES, " ", v)
    v = re.sub(r"[^a-z0-9äöüßåæøéèàìòù ]", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def similarity(a: str | None, b: str | None) -> float:
    a_n, b_n = normalize_name(a), normalize_name(b)
    if not a_n or not b_n:
        return 0.0
    if a_n in b_n or b_n in a_n:
        return 0.95
    return difflib.SequenceMatcher(None, a_n, b_n).ratio()


def close_enough(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(TOLERANCE_ABS, abs(b) * TOLERANCE_REL)


def match_vendor(inv: ExtractedInvoice, vendors: list[dict[str, Any]]) -> dict[str, Any] | None:
    tax = normalize_code(inv.vendor_tax_id)
    if tax:
        for v in vendors:
            if normalize_code(v["VatId"]) == tax:
                return v
    best, best_score = None, 0.0
    for v in vendors:
        score = similarity(inv.vendor_name, v["VendorName"])
        if score > best_score:
            best, best_score = v, score
    return best if best_score >= 0.75 else None


# ------------------------------------------------------------------ validation
def validate(inv: ExtractedInvoice, ref: dict[str, Any], vendor: dict[str, Any] | None,
             duplicate_ids: list[int], max_amount: Decimal, min_confidence: float,
             today: date | None = None) -> Validation:
    today = today or date.today()
    present = sum(x is not None for x in (inv.invoice_id, inv.vendor_name, inv.total))
    is_invoice = present >= 2 and (inv.total is not None or bool(inv.lines))
    po = ref.get("po")
    val = Validation(is_invoice=is_invoice, vendor=vendor, po=None, lines=[], min_confidence=inv.min_confidence())
    if not is_invoice:
        val.checks.append(Check("Looks like an invoice", False,
                                "This doesn't look like an invoice (no invoice number, vendor or total found)."))
        return val
    checks = val.checks

    # Vendor
    checks.append(Check("Vendor is known", vendor is not None,
                        f"Vendor matched: {vendor['VendorName']}." if vendor else
                        f"Unknown vendor '{inv.vendor_name or '?'}' - not in vendor master data."))

    # Purchase order
    checks.append(Check("Purchase order on invoice", bool(inv.po_number),
                        f"PO number {inv.po_number}." if inv.po_number else "No purchase order number on the invoice."))
    if inv.po_number:
        if po is None:
            checks.append(Check("Purchase order exists", False, f"Purchase order {inv.po_number} not found."))
        elif vendor and po["VendorId"] != vendor["VendorId"]:
            checks.append(Check("Purchase order exists", False,
                                f"Purchase order {po['PONumber']} belongs to a different vendor."))
            po = None
        else:
            checks.append(Check("Purchase order exists", True, f"Purchase order {po['PONumber']} found."))
            val.po = po

    # Duplicates
    if inv.invoice_id and vendor:
        checks.append(Check("Not a duplicate", not duplicate_ids,
                            "No earlier invoice with this number." if not duplicate_ids else
                            f"Invoice {inv.invoice_id} was already submitted (invoice #{duplicate_ids[0]})."))

    # Lines: match to products, contract prices, PO quantities, goods receipts
    products = ref.get("products", [])
    po_lines = {l["ProductId"]: l for l in (val.po or {}).get("lines", [])}
    candidates = [p for p in products if p["ProductId"] in po_lines] or \
                 [p for p in products if vendor and p["VendorId"] == vendor["VendorId"]] or products
    unmatched, over_qty, price_issues = [], [], []
    max_dev: Decimal | None = None
    for line in inv.lines:
        product = _match_product(line.product_code, line.description, candidates)
        ml = MatchedLine(description=line.description, sku=line.product_code, product_id=None,
                         quantity=line.quantity, unit_price=line.unit_price, amount=line.amount)
        if ml.unit_price is None and ml.amount is not None and ml.quantity:
            ml.unit_price = (ml.amount / ml.quantity).quantize(Decimal("0.01"))
        if ml.amount is None and ml.unit_price is not None and ml.quantity is not None:
            ml.amount = (ml.unit_price * ml.quantity).quantize(Decimal("0.01"))
        if product:
            ml.product_id = product["ProductId"]
            ml.sku = product["Sku"]
            if product.get("ContractPrice") is not None:
                ml.contract_price = Decimal(str(product["ContractPrice"]))
                ml.max_deviation_pct = Decimal(str(product.get("MaxPriceDeviationPct") or 2))
                if ml.unit_price is not None and ml.contract_price:
                    ml.deviation_pct = ((ml.unit_price - ml.contract_price) / ml.contract_price * 100).quantize(Decimal("0.01"))
                    max_dev = ml.deviation_pct if max_dev is None else max(max_dev, ml.deviation_pct)
                    if ml.deviation_pct > ml.max_deviation_pct:
                        price_issues.append(f"{product['ProductName']}: {ml.unit_price} vs contract {ml.contract_price} "
                                            f"(+{ml.deviation_pct}%)")
            pol = po_lines.get(product["ProductId"])
            if pol:
                ml.po_quantity = Decimal(str(pol["Quantity"]))
                ml.received_quantity = Decimal(str(pol["ReceivedQuantity"]))
                if ml.quantity is not None and (ml.quantity > ml.po_quantity or ml.quantity > ml.received_quantity):
                    over_qty.append(f"{product['ProductName']}: invoiced {ml.quantity}, received {ml.received_quantity}")
            elif val.po:
                unmatched.append(line.description or line.product_code or "?")
        else:
            unmatched.append(line.description or line.product_code or "?")
        val.lines.append(ml)
    val.max_deviation_pct = max_dev

    if not inv.lines:
        checks.append(Check("Line items found", False, "No line items could be read."))
    else:
        checks.append(Check("Lines match the purchase order", not unmatched,
                            "All lines match ordered products." if not unmatched else
                            f"Lines not on the purchase order: {', '.join(unmatched[:3])}."))
        if val.po:
            checks.append(Check("Goods received", not over_qty,
                                "Invoiced quantities were received." if not over_qty else
                                f"More invoiced than received: {'; '.join(over_qty[:3])}."))
        checks.append(Check("Prices within contract", not price_issues,
                            "Prices match the contract." if not price_issues else
                            f"Price above contract: {'; '.join(price_issues[:3])}."))

    # Totals
    line_sum = sum((l.amount for l in val.lines if l.amount is not None), Decimal("0"))
    total_problems = []
    if inv.subtotal is not None and val.lines and not close_enough(line_sum, inv.subtotal):
        total_problems.append(f"lines add up to {line_sum}, subtotal says {inv.subtotal}")
    if inv.total is not None:
        base = inv.subtotal if inv.subtotal is not None else line_sum
        if inv.tax is not None:
            expected_totals = [base + inv.tax]
        else:  # tax not read: accept the common VAT rates (0 % reverse charge, 10/13/20 % Austria)
            expected_totals = [(base * (1 + r)).quantize(Decimal("0.01")) for r in
                               (Decimal("0"), Decimal("0.10"), Decimal("0.13"), Decimal("0.20"))]
        if base and not any(close_enough(e, inv.total) for e in expected_totals):
            total_problems.append(f"subtotal + tax = {expected_totals[0]}, total says {inv.total}")
    checks.append(Check("Totals add up", not total_problems,
                        "Line items, tax and total are consistent." if not total_problems else
                        f"Totals don't add up: {'; '.join(total_problems)}."))

    # Confidence of the most important fields
    if val.min_confidence is not None:
        checks.append(Check("Read with high confidence", val.min_confidence >= min_confidence,
                            f"Lowest confidence of key fields: {val.min_confidence:.2f}." if val.min_confidence >= min_confidence
                            else f"Some key fields were hard to read (confidence {val.min_confidence:.2f} < {min_confidence:.2f})."))

    # Amount limit and currency
    if inv.total is not None:
        checks.append(Check("Within auto-approval limit", inv.total <= max_amount,
                            f"Total {inv.total} is within the limit of {max_amount}." if inv.total <= max_amount else
                            f"Total {inv.total} exceeds the auto-approval limit of {max_amount}."))
    if inv.currency and inv.currency != "EUR":
        checks.append(Check("Currency is EUR", False, f"Invoice currency is {inv.currency}, contracts are in EUR."))
    if inv.invoice_date and inv.invoice_date > today:
        checks.append(Check("Invoice date not in the future", False, f"Invoice date {inv.invoice_date} is in the future."))
    return val


def _match_product(code: str | None, description: str | None, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    norm = normalize_code(code)
    if norm:
        for p in candidates:
            if normalize_code(p["Sku"]) == norm:
                return p
    # the SKU is often printed inside the description
    for p in candidates:
        if normalize_code(p["Sku"]) and normalize_code(p["Sku"]) in normalize_code(description):
            return p
    best, best_score = None, 0.0
    for p in candidates:
        score = difflib.SequenceMatcher(None, (description or "").lower(), p["ProductName"].lower()).ratio()
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 0.6 else None


# ------------------------------------------------------------------ decision
def decide(val: Validation, review: ReviewOpinion | None) -> Decision:
    if not val.is_invoice or (review and review.not_an_invoice and not val.vendor):
        return Decision("NotAnInvoice", [c.detail for c in val.failed] or ["This doesn't look like an invoice."],
                        "NotAnInvoice")
    reasons = [c.detail for c in val.failed]
    if review is None:
        reasons.append("Review agent unavailable, so a person checks it to be safe.")
    else:
        if review.injection_detected:
            reasons.insert(0, "The document contains instructions aimed at the AI (possible prompt injection).")
        if review.manual_alteration_detected:
            reasons.append("Amounts look manually altered.")
        if review.recommendation != "approve":
            reasons.append(f"Review agent: {review.summary or 'recommends a human check.'}")
    if reasons:
        return Decision("NeedsReview", reasons, "RoutedToReview")
    return Decision("AutoApproved", [], "AutoApproved")
