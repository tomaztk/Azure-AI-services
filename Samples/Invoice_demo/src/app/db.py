"""Azure SQL access (mssql-python driver, Microsoft Entra authentication, no passwords).

All functions are synchronous; the async web layer calls them through asyncio.to_thread.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import mssql_python

from .config import get_settings


def _conn_str() -> str:
    s = get_settings()
    return (f"Server=tcp:{s.sql_server},1433;Database={s.sql_database};"
            f"Authentication={s.sql_authentication};Encrypt=yes;TrustServerCertificate=no;")


@contextmanager
def connect() -> Iterator[Any]:
    """Open a (pooled) connection; commit on success, roll back on error."""
    conn = mssql_python.connect(_conn_str(), timeout=30)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows_as_dicts(cursor) -> list[dict[str, Any]]:
    if not cursor.description:
        return []
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return rows_as_dicts(cur)


def to_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    return value


# ------------------------------------------------------------------ invoices
def create_invoice(source: str, session_id: str | None, content_type: str) -> int:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO dbo.Invoices (Status, ProcessingStage, Source, SessionId, ContentType)
               OUTPUT INSERTED.InvoiceId
               VALUES (N'Processing', N'uploaded', ?, ?, ?);""",
            (source, session_id, content_type),
        )
        return int(cur.fetchone()[0])


def set_stage(invoice_id: int, stage: str, blob_path: str | None = None) -> None:
    with connect() as conn:
        cur = conn.cursor()
        if blob_path:
            cur.execute("UPDATE dbo.Invoices SET ProcessingStage = ?, BlobPath = ? WHERE InvoiceId = ?",
                        (stage, blob_path, invoice_id))
        else:
            cur.execute("UPDATE dbo.Invoices SET ProcessingStage = ? WHERE InvoiceId = ?", (stage, invoice_id))


def load_reference_data(vendor_hint: str | None, po_number: str | None) -> dict[str, Any]:
    """Everything the validation rules need, in one round trip per table."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT VendorId, VendorCode, VendorName, VatId, Iban, CountryCode FROM dbo.Vendors")
        vendors = rows_as_dicts(cur)
        cur.execute("""SELECT p.ProductId, p.Sku, p.ProductName, p.PreferredVendorId AS VendorId,
                              c.UnitPrice AS ContractPrice, c.MaxPriceDeviationPct, c.Currency, c.ValidFrom, c.ValidTo
                       FROM dbo.Products p
                       LEFT JOIN dbo.Contracts c ON c.ProductId = p.ProductId AND c.VendorId = p.PreferredVendorId""")
        products = rows_as_dicts(cur)
        po = None
        if po_number:
            cur.execute("""SELECT PurchaseOrderId, PONumber, VendorId, OrderDate, Status, Currency, TotalAmount
                           FROM dbo.PurchaseOrders WHERE UPPER(REPLACE(REPLACE(PONumber, ' ', ''), '-', '')) = ?""",
                        (normalize_code(po_number),))
            found = rows_as_dicts(cur)
            if found:
                po = found[0]
                cur.execute("""SELECT l.LineNumber, l.ProductId, l.Quantity, l.UnitPrice,
                                      ISNULL((SELECT SUM(g.ReceivedQuantity) FROM dbo.GoodsReceipts g
                                              WHERE g.PurchaseOrderId = l.PurchaseOrderId AND g.ProductId = l.ProductId), 0) AS ReceivedQuantity
                               FROM dbo.PurchaseOrderLines l WHERE l.PurchaseOrderId = ?""", (po["PurchaseOrderId"],))
                po["lines"] = rows_as_dicts(cur)
        return {"vendors": vendors, "products": products, "po": po}


def normalize_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def find_duplicates(vendor_id: int, invoice_number: str, exclude_invoice_id: int,
                    source: str, session_id: str | None) -> list[int]:
    """Approved/pending invoices with the same vendor and number. Audience scans only compete within one phone."""
    sql = """SELECT InvoiceId FROM dbo.Invoices
             WHERE VendorId = ? AND InvoiceNumber = ? AND InvoiceId <> ?
               AND Status IN (N'AutoApproved', N'Approved', N'NeedsReview')"""
    params: list[Any] = [vendor_id, invoice_number, exclude_invoice_id]
    if source == "audience":
        sql += " AND Source = N'audience' AND SessionId = ?"
        params.append(session_id)
    else:
        sql += " AND Source <> N'audience'"
    return [r["InvoiceId"] for r in query(sql, tuple(params))]


def save_result(invoice_id: int, header: dict[str, Any], lines: list[dict[str, Any]], log_action: str,
                log_actor: str, log_comment: str) -> None:
    """Write the extracted header, the lines and the decision in one transaction."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE dbo.Invoices SET
                   InvoiceNumber = ?, VendorId = ?, VendorNameRaw = ?, PONumber = ?, PurchaseOrderId = ?,
                   InvoiceDate = ?, DueDate = ?, Currency = ?, SubtotalAmount = ?, TaxAmount = ?, TotalAmount = ?,
                   Status = ?, ProcessingStage = N'done', DecisionType = ?, DecisionReason = ?,
                   MinFieldConfidence = ?, MaxPriceDeviationPct = ?, DecidedAt = ?, DecidedBy = ?, ProcessingMs = ?
               WHERE InvoiceId = ?""",
            (header.get("InvoiceNumber"), header.get("VendorId"), header.get("VendorNameRaw"), header.get("PONumber"),
             header.get("PurchaseOrderId"), header.get("InvoiceDate"), header.get("DueDate"), header.get("Currency"),
             header.get("SubtotalAmount"), header.get("TaxAmount"), header.get("TotalAmount"),
             header["Status"], header.get("DecisionType"), header.get("DecisionReason"),
             header.get("MinFieldConfidence"), header.get("MaxPriceDeviationPct"), header.get("DecidedAt"),
             header.get("DecidedBy"), header.get("ProcessingMs"), invoice_id),
        )
        cur.execute("DELETE FROM dbo.InvoiceLines WHERE InvoiceId = ?", (invoice_id,))
        for i, line in enumerate(lines, start=1):
            cur.execute(
                """INSERT INTO dbo.InvoiceLines (InvoiceId, LineNumber, ProductId, Sku, Description, Quantity,
                                                 UnitPrice, LineAmount, ContractUnitPrice, PriceDeviationPct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (invoice_id, i, line.get("ProductId"), line.get("Sku"), (line.get("Description") or "")[:300],
                 line.get("Quantity"), line.get("UnitPrice"), line.get("LineAmount"),
                 line.get("ContractUnitPrice"), line.get("PriceDeviationPct")),
            )
        cur.execute("INSERT INTO dbo.ApprovalLog (InvoiceId, Action, Actor, Comment) VALUES (?, ?, ?, ?)",
                    (invoice_id, log_action, log_actor, (log_comment or "")[:1000]))


def mark_failed(invoice_id: int, reason: str, processing_ms: int | None = None) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""UPDATE dbo.Invoices SET Status = N'Failed', ProcessingStage = N'done', DecisionReason = ?,
                              ProcessingMs = ? WHERE InvoiceId = ?""", (reason[:1000], processing_ms, invoice_id))
        cur.execute("INSERT INTO dbo.ApprovalLog (InvoiceId, Action, Actor, Comment) VALUES (?, N'Failed', N'ai-intake', ?)",
                    (invoice_id, reason[:1000]))


def fail_stale_processing(minutes: int = 10) -> int:
    """After a restart, invoices stuck in 'Processing' will never finish; mark them failed."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""UPDATE dbo.Invoices SET Status = N'Failed', ProcessingStage = N'done',
                              DecisionReason = N'Processing was interrupted (app restart). Please scan again.'
                       WHERE Status = N'Processing' AND ReceivedAt < DATEADD(minute, ?, SYSUTCDATETIME())""", (-minutes,))
        return cur.rowcount


def decide_manually(invoice_id: int, approve: bool, actor: str, comment: str | None) -> bool:
    status = "Approved" if approve else "Rejected"
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""UPDATE dbo.Invoices SET Status = ?, DecisionType = N'Manual', DecidedAt = SYSUTCDATETIME(),
                              DecidedBy = ?, DecisionReason = COALESCE(?, DecisionReason)
                       WHERE InvoiceId = ? AND Status IN (N'NeedsReview', N'AutoApproved', N'Failed')""",
                    (status, actor, comment, invoice_id))
        if cur.rowcount == 0:
            return False
        cur.execute("INSERT INTO dbo.ApprovalLog (InvoiceId, Action, Actor, Comment) VALUES (?, ?, ?, ?)",
                    (invoice_id, status, actor, comment))
        return True


def get_invoice(invoice_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT i.InvoiceId, i.InvoiceNumber, i.VendorId, COALESCE(v.VendorName, i.VendorNameRaw) AS VendorName,
                              i.PONumber, i.InvoiceDate, i.DueDate, i.Currency, i.SubtotalAmount, i.TaxAmount, i.TotalAmount,
                              i.Status, i.ProcessingStage, i.DecisionType, i.DecisionReason, i.MinFieldConfidence,
                              i.MaxPriceDeviationPct, i.Source, i.SessionId, i.BlobPath, i.ContentType, i.ReceivedAt, i.DecidedAt, i.DecidedBy, i.ProcessingMs
                       FROM dbo.Invoices i LEFT JOIN dbo.Vendors v ON v.VendorId = i.VendorId
                       WHERE i.InvoiceId = ?""", (invoice_id,))
        rows = rows_as_dicts(cur)
        if not rows:
            return None
        inv = rows[0]
        cur.execute("""SELECT LineNumber, Sku, Description, Quantity, UnitPrice, LineAmount, ContractUnitPrice, PriceDeviationPct
                       FROM dbo.InvoiceLines WHERE InvoiceId = ? ORDER BY LineNumber""", (invoice_id,))
        inv["Lines"] = rows_as_dicts(cur)
        return inv


def feed(limit: int = 30) -> dict[str, Any]:
    """Presenter screen: counters for today's live invoices, the review queue and the latest events."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""SELECT Status, Source, COUNT(*) AS N, AVG(CAST(ProcessingMs AS float)) AS AvgMs
                       FROM dbo.Invoices
                       WHERE Source <> N'legacy' AND ReceivedAt >= DATEADD(hour, -12, SYSUTCDATETIME())
                       GROUP BY Status, Source""")
        counters = rows_as_dicts(cur)
        cur.execute(f"""SELECT TOP ({int(limit)}) i.InvoiceId, i.InvoiceNumber, COALESCE(v.VendorName, i.VendorNameRaw) AS VendorName,
                               i.TotalAmount, i.Currency, i.Status, i.ProcessingStage, i.DecisionReason, i.Source,
                               i.ReceivedAt, i.ProcessingMs, i.MaxPriceDeviationPct
                        FROM dbo.Invoices i LEFT JOIN dbo.Vendors v ON v.VendorId = i.VendorId
                        WHERE i.Source <> N'legacy'
                        ORDER BY i.InvoiceId DESC""")
        recent = rows_as_dicts(cur)
        cur.execute("""SELECT TOP (50) i.InvoiceId, i.InvoiceNumber, COALESCE(v.VendorName, i.VendorNameRaw) AS VendorName,
                              i.TotalAmount, i.Currency, i.DecisionReason, i.Source, i.ReceivedAt,
                              i.MaxPriceDeviationPct, i.MinFieldConfidence
                       FROM dbo.Invoices i LEFT JOIN dbo.Vendors v ON v.VendorId = i.VendorId
                       WHERE i.Status = N'NeedsReview'
                       ORDER BY CASE WHEN i.Source = N'stage' THEN 0 ELSE 1 END, i.InvoiceId DESC""")
        queue = rows_as_dicts(cur)
        cur.execute("""SELECT TOP (20) QuestionId, Question, LEFT(Answer, 400) AS Answer, AskedAt, DurationMs
                       FROM dbo.AudienceQuestions ORDER BY QuestionId DESC""")
        questions = rows_as_dicts(cur)
    return {"counters": counters, "recent": recent, "queue": queue, "questions": questions}


def log_question(session_id: str | None, question: str, answer: str, tools: list[str], duration_ms: int) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO dbo.AudienceQuestions (SessionId, Question, Answer, ToolsUsed, DurationMs)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, question[:500], answer[:4000], ",".join(tools)[:400], duration_ms))


def data_as_of() -> str | None:
    rows = query("SELECT CONVERT(char(10), MAX(OrderDate), 23) AS AsOf FROM dbo.SalesOrders")
    return rows[0]["AsOf"] if rows else None
