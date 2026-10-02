"""Azure Content Understanding (Foundry Tools): extract invoice fields from a photo or PDF.

Uses the GA REST API (2025-11-01) directly so the call is easy to show on stage:
  POST {endpoint}/contentunderstanding/analyzers/prebuilt-invoice:analyzeBinary  -> 202 + Operation-Location
  GET  Operation-Location until status == Succeeded
Authentication: Microsoft Entra ID (managed identity in Azure, your login locally).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential

API_VERSION = "2025-11-01"
SCOPE = "https://cognitiveservices.azure.com/.default"


class ContentUnderstandingError(RuntimeError):
    pass


class ContentUnderstandingClient:
    def __init__(self, endpoint: str, credential: DefaultAzureCredential | None = None, timeout_s: int = 120):
        self.endpoint = endpoint.rstrip("/")
        self.credential = credential or DefaultAzureCredential()
        self.timeout_s = timeout_s
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))

    async def _headers(self) -> dict[str, str]:
        token = await asyncio.to_thread(self.credential.get_token, SCOPE)  # cached by azure-identity
        return {"Authorization": f"Bearer {token.token}"}

    async def analyze(self, data: bytes, content_type: str, analyzer_id: str = "prebuilt-invoice") -> dict[str, Any]:
        """Analyze a file and return the `result` object of the finished operation."""
        url = f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyzeBinary"
        headers = await self._headers()
        headers["Content-Type"] = content_type or "application/octet-stream"
        resp = await self._http.post(url, params={"api-version": API_VERSION}, headers=headers, content=data)
        if resp.status_code != 202:
            raise ContentUnderstandingError(f"analyze failed: {resp.status_code} {resp.text[:500]}")
        operation_url = resp.headers["Operation-Location"]

        deadline = time.monotonic() + self.timeout_s
        delay = 1.0
        while time.monotonic() < deadline:
            await asyncio.sleep(delay)
            poll = await self._http.get(operation_url, headers=await self._headers())
            poll.raise_for_status()
            body = poll.json()
            status = body.get("status", "").lower()
            if status == "succeeded":
                return body["result"]
            if status in ("failed", "canceled", "cancelled"):
                raise ContentUnderstandingError(f"analysis {status}: {body.get('error')}")
            delay = min(delay * 1.3, 3.0)
        raise ContentUnderstandingError("analysis timed out")

    async def aclose(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------------------------
# Parsing the prebuilt-invoice result into a small, typed structure
# ---------------------------------------------------------------------------------------------
@dataclass
class ExtractedLine:
    description: str | None = None
    product_code: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


@dataclass
class ExtractedInvoice:
    invoice_id: str | None = None
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    vendor_address: str | None = None
    customer_name: str | None = None
    po_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    lines: list[ExtractedLine] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    markdown: str = ""

    def min_confidence(self, keys: tuple[str, ...] = ("InvoiceId", "VendorName", "TotalAmount", "PONumber")) -> float | None:
        values = [self.confidence[k] for k in keys if k in self.confidence]
        return min(values) if values else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice_id, "vendor_name": self.vendor_name, "vendor_tax_id": self.vendor_tax_id,
            "customer_name": self.customer_name, "po_number": self.po_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "currency": self.currency, "subtotal": _f(self.subtotal), "tax": _f(self.tax), "total": _f(self.total),
            "lines": [{"description": l.description, "product_code": l.product_code, "quantity": _f(l.quantity),
                       "unit_price": _f(l.unit_price), "amount": _f(l.amount)} for l in self.lines],
            "confidence": self.confidence,
        }


def _f(d: Decimal | None) -> float | None:
    return float(d) if d is not None else None


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _value(f: dict[str, Any] | None) -> Any:
    if not f:
        return None
    for key in ("valueString", "valueNumber", "valueInteger", "valueDate", "valueTime", "valueBoolean",
                "valueObject", "valueArray", "valueCurrency"):
        if key in f:
            return f[key]
    return None


def _amount(f: dict[str, Any] | None) -> tuple[Decimal | None, str | None, float | None]:
    """Amount fields are objects: {Amount: number, CurrencyCode: string}."""
    obj = _value(f)
    if isinstance(obj, dict):
        amount = obj.get("Amount")
        currency = obj.get("CurrencyCode")
        return _dec(_value(amount)), _value(currency), (amount or {}).get("confidence")
    if obj is not None:  # plain number
        return _dec(obj), None, (f or {}).get("confidence")
    return None, None, None


def _date(f: dict[str, Any] | None) -> date | None:
    v = _value(f)
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def parse_invoice(result: dict[str, Any]) -> ExtractedInvoice:
    contents = result.get("contents") or []
    if not contents:
        return ExtractedInvoice()
    content = contents[0]
    fields: dict[str, Any] = content.get("fields") or {}
    inv = ExtractedInvoice(markdown=content.get("markdown") or "")

    def text(name: str) -> str | None:
        f = fields.get(name)
        v = _value(f)
        if f and f.get("confidence") is not None:
            inv.confidence[name] = float(f["confidence"])
        return str(v).strip() if v not in (None, "") else None

    inv.invoice_id = text("InvoiceId")
    inv.vendor_name = text("VendorName")
    inv.vendor_tax_id = text("VendorTaxId")
    inv.vendor_address = text("VendorAddress")
    inv.customer_name = text("CustomerName")
    inv.po_number = text("PONumber") or text("PurchaseOrder")
    inv.invoice_date = _date(fields.get("InvoiceDate"))
    inv.due_date = _date(fields.get("DueDate"))

    total, currency, conf = _amount(fields.get("TotalAmount"))
    if total is None:
        total, currency, conf = _amount(fields.get("AmountDue"))
    inv.total = total
    if conf is not None:
        inv.confidence["TotalAmount"] = float(conf)
    inv.subtotal, cur2, _ = _amount(fields.get("SubtotalAmount"))
    inv.tax, cur3, _ = _amount(fields.get("TotalTaxAmount"))
    inv.currency = (currency or cur2 or cur3 or "").upper() or None

    for item in _value(fields.get("LineItems")) or []:
        obj = _value(item) or {}
        if not isinstance(obj, dict):
            continue
        unit_price, _, _ = _amount(obj.get("UnitPrice"))
        amount, _, _ = _amount(obj.get("TotalAmount"))
        inv.lines.append(ExtractedLine(
            description=_value(obj.get("Description")),
            product_code=_value(obj.get("ProductCode")),
            quantity=_dec(_value(obj.get("Quantity"))),
            unit_price=unit_price,
            amount=amount,
        ))
    return inv
