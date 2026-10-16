"""The invoice intake pipeline: one function you can walk through on stage.

  upload -> store -> extract (Content Understanding) -> check (rules + master data)
         -> decide -> write to Azure SQL
The data agent then answers questions from the same database.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from . import db, rules
from .config import get_settings
from .content_understanding import ContentUnderstandingClient, ExtractedInvoice, parse_invoice
from .storage import DocumentStore

log = logging.getLogger(__name__)


class InvoicePipeline:
    def __init__(self, cu: ContentUnderstandingClient, store: DocumentStore) -> None:
        self.cu = cu
        self.store = store
        self.settings = get_settings()
        # Protects Content Understanding and the model quota when 100 phones upload at once.
        self._slots = asyncio.Semaphore(self.settings.max_concurrent_extractions)

    async def process(self, invoice_id: int, data: bytes, content_type: str, source: str,
                      session_id: str | None) -> None:
        started = time.monotonic()
        try:
            # 1. Keep the original document
            blob_path = await asyncio.to_thread(self.store.save_upload, invoice_id, source, data, content_type)
            await asyncio.to_thread(db.set_stage, invoice_id, "reading", blob_path)

            # 2. Extract fields with Content Understanding (prebuilt-invoice analyzer)
            async with self._slots:
                result = await self.cu.analyze(data, content_type)
            await asyncio.to_thread(self.store.save_extraction, invoice_id, source, result)
            invoice = parse_invoice(result)

            # 3. Check against master data: vendor, purchase order, goods receipt, contract, totals
            await asyncio.to_thread(db.set_stage, invoice_id, "checking")
            ref = await asyncio.to_thread(db.load_reference_data, invoice.vendor_name, invoice.po_number)
            vendor = rules.match_vendor(invoice, ref["vendors"])
            duplicates = []
            if vendor and invoice.invoice_id:
                duplicates = await asyncio.to_thread(db.find_duplicates, vendor["VendorId"], invoice.invoice_id,
                                                     invoice_id, source, session_id)
            validation = rules.validate(invoice, ref, vendor, duplicates, self.settings.auto_approve_max_amount,
                                        self.settings.min_field_confidence)

            # 4. Decide and write header, lines and an audit entry to Azure SQL
            decision = rules.decide(validation)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            header = self._header(invoice, validation, decision, elapsed_ms)
            await asyncio.to_thread(db.save_result, invoice_id, header,
                                    [l.as_db_row() for l in validation.lines],
                                    decision.log_action, "ai-intake", decision.reason_text)
            log.info("invoice %s -> %s in %d ms", invoice_id, decision.status, elapsed_ms)
        except Exception as ex:
            log.exception("invoice %s failed", invoice_id)
            await asyncio.to_thread(db.mark_failed, invoice_id, f"Processing failed: {ex}",
                                    int((time.monotonic() - started) * 1000))

    @staticmethod
    def _header(invoice: ExtractedInvoice, v: rules.Validation, decision: rules.Decision,
                elapsed_ms: int) -> dict[str, Any]:
        auto = decision.status == "AutoApproved"
        return {
            "InvoiceNumber": (invoice.invoice_id or "")[:60] or None,
            "VendorId": v.vendor["VendorId"] if v.vendor else None,
            "VendorNameRaw": (invoice.vendor_name or "")[:200] or None,
            "PONumber": (invoice.po_number or "")[:40] or None,
            "PurchaseOrderId": v.po["PurchaseOrderId"] if v.po else None,
            "InvoiceDate": invoice.invoice_date, "DueDate": invoice.due_date,
            "Currency": (invoice.currency or "")[:3] or None,
            "SubtotalAmount": _money(invoice.subtotal), "TaxAmount": _money(invoice.tax), "TotalAmount": _money(invoice.total),
            "Status": decision.status,
            "DecisionType": "Auto" if decision.status in ("AutoApproved", "NotAnInvoice") else None,
            "DecisionReason": decision.reason_text[:1000],
            "MinFieldConfidence": round(v.min_confidence, 3) if v.min_confidence is not None else None,
            "MaxPriceDeviationPct": v.max_deviation_pct,
            "DecidedAt": datetime.now(timezone.utc).replace(tzinfo=None) if auto else None,
            "DecidedBy": "ai-intake" if auto else None,
            "ProcessingMs": elapsed_ms,
        }


def _money(d: Decimal | None) -> Decimal | None:
    if d is None or abs(d) >= Decimal("1e11"):  # doesn't fit decimal(14,2); garbage from a bad scan
        return None
    return d.quantize(Decimal("0.01"))
