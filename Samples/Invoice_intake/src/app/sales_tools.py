"""Python implementations of the sales agent's function tools.

The agent never writes SQL. It picks a tool and arguments; this module turns them into
fixed, parameterized queries against the analytical views. Row-level security in Azure SQL
filters the rows by the persona that is set on the connection.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any, Callable

from . import db

MAX_ROWS = 25
_as_of_cache: dict[str, Any] = {"value": None, "at": 0.0}


def sales_as_of() -> date:
    """Latest order date in the data (the demo's 'today' for sales questions)."""
    if _as_of_cache["value"] is None or time.monotonic() - _as_of_cache["at"] > 300:
        value = db.data_as_of()
        _as_of_cache["value"] = date.fromisoformat(value) if value else date.today()
        _as_of_cache["at"] = time.monotonic()
    return _as_of_cache["value"]


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def resolve_period(period: str, as_of: date, start: str | None = None, end: str | None = None) -> tuple[date, date, str]:
    first_of_month = as_of.replace(day=1)
    if period == "custom" and start and end:
        s, e = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
        return s, e, f"{s} to {e}"
    if period == "last_30_days":
        return as_of - timedelta(days=29), as_of, "the last 30 days"
    if period == "this_month":
        return first_of_month, as_of, f"{as_of:%B %Y} (month to date)"
    if period == "last_month":
        e = first_of_month - timedelta(days=1)
        return e.replace(day=1), e, f"{e:%B %Y}"
    if period == "this_quarter":
        s = _quarter_start(as_of)
        return s, as_of, f"Q{(s.month - 1) // 3 + 1} {s.year} (quarter to date)"
    if period == "last_quarter":
        e = _quarter_start(as_of) - timedelta(days=1)
        s = _quarter_start(e)
        return s, e, f"Q{(s.month - 1) // 3 + 1} {s.year}"
    if period == "year_to_date":
        return date(as_of.year, 1, 1), as_of, f"{as_of.year} year to date"
    if period == "last_12_months":
        s = date(as_of.year - 1, as_of.month, 1)
        return s, as_of, "the last 12 months"
    return date(2000, 1, 1), as_of, "all available history"


def _like(value: str | None) -> str | None:
    return f"%{value.strip()}%" if value and value.strip() else None


def _region_filter(region: str | None, params: list[Any]) -> str:
    if not region:
        return ""
    params.extend([_like(region), region.strip().upper()])
    return " AND (RegionName LIKE ? OR RegionCode = ?)"


def _product_filter(product: str | None, params: list[Any]) -> str:
    if not product:
        return ""
    words = [w for w in product.replace("-", " ").split() if w]
    clause = ""
    for w in words[:4]:  # every word must match the name or SKU ("battery 500" -> Battery Pack 500Wh)
        clause += " AND (ProductName LIKE ? OR Sku LIKE ?)"
        params.extend([f"%{w}%", f"%{w}%"])
    return clause


# ------------------------------------------------------------------ tools
GROUP_COLUMNS = {"region": "RegionName", "product": "ProductName", "category": "Category",
                 "customer": "CustomerName", "supplier": "SupplierName", "month": "YearMonth", "channel": "Channel"}
ORDER_COLUMNS = {"revenue": "revenue", "gross_margin": "gross_margin", "margin_pct": "margin_pct", "units": "units"}


def get_sales_summary(persona: str, period: str, start_date=None, end_date=None, group_by="none",
                      order_by="revenue", top_n=None, region=None, product=None) -> dict[str, Any]:
    s, e, label = resolve_period(period, sales_as_of(), start_date, end_date)
    params: list[Any] = []
    top = max(1, min(int(top_n or (MAX_ROWS if group_by == "month" else 10)), MAX_ROWS))
    group_col = GROUP_COLUMNS.get(group_by)
    select_group = f"{group_col} AS [group]" if group_col else "N'Total' AS [group]"
    order_col = ORDER_COLUMNS.get(order_by, "revenue")
    # months: take the latest N, return them in chronological order
    order_clause = "ORDER BY [group] DESC" if group_by == "month" else f"ORDER BY {order_col} DESC"
    sql = f"""SELECT TOP ({top}) {select_group},
                  SUM(Revenue) AS revenue, SUM(CostAmount) AS purchase_cost, SUM(GrossMargin) AS gross_margin,
                  CAST(100.0 * SUM(GrossMargin) / NULLIF(SUM(Revenue), 0) AS decimal(6,1)) AS margin_pct,
                  SUM(Quantity) AS units, COUNT(DISTINCT SalesOrderId) AS orders
              FROM dbo.vw_SalesLines
              WHERE OrderDate BETWEEN ? AND ?"""
    params.extend([s, e])
    sql += _region_filter(region, params) + _product_filter(product, params)
    if group_col:
        sql += f" GROUP BY {group_col}"
    sql += f" {order_clause}"
    rows = db.query(sql, tuple(params), persona=persona)
    rows = [r for r in rows if r.get("revenue") is not None]
    if group_by == "month":
        rows.reverse()
    return {"period": label, "from": s, "to": e, "rows": rows}


def get_margin_trend(persona: str, months: int = 6, product=None, region=None) -> dict[str, Any]:
    as_of = sales_as_of()
    months = max(3, min(int(months or 6), 18))
    start = as_of.replace(day=1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    params: list[Any] = [start, as_of]
    sql = """SELECT YearMonth AS month, SUM(Revenue) AS revenue, SUM(GrossMargin) AS gross_margin,
                    CAST(100.0 * SUM(GrossMargin) / NULLIF(SUM(Revenue), 0) AS decimal(6,1)) AS margin_pct,
                    CAST(SUM(CostAmount) / NULLIF(SUM(Quantity), 0) AS decimal(12,2)) AS avg_unit_cost,
                    SUM(Quantity) AS units
             FROM dbo.vw_SalesLines WHERE OrderDate BETWEEN ? AND ?"""
    sql += _region_filter(region, params) + _product_filter(product, params)
    sql += " GROUP BY YearMonth ORDER BY YearMonth"
    return {"from": start, "to": as_of, "note": f"The last month is partial (data as of {as_of}).",
            "rows": db.query(sql, tuple(params), persona=persona)}


def get_supplier_price_deviations(persona: str, period: str, start_date=None, end_date=None, supplier=None) -> dict[str, Any]:
    s, e, label = resolve_period(period, max(date.today(), sales_as_of()), start_date, end_date)
    params: list[Any] = [s, e]
    sql = """SELECT TOP (25) VendorName AS supplier, ProductName AS product, Sku AS sku,
                    COUNT(DISTINCT InvoiceId) AS invoices,
                    CAST(AVG(PriceDeviationPct) AS decimal(7,2)) AS avg_deviation_pct,
                    MAX(PriceDeviationPct) AS max_deviation_pct,
                    SUM(OverpaymentAmount) AS overpayment_eur,
                    MIN(YearMonth) AS first_month, MAX(YearMonth) AS last_month,
                    SUM(CASE WHEN Status IN (N'AutoApproved', N'Approved') THEN 1 ELSE 0 END) AS approved_lines,
                    SUM(CASE WHEN Status = N'NeedsReview' THEN 1 ELSE 0 END) AS lines_waiting_for_review
             FROM dbo.vw_InvoiceLineDeviations
             WHERE InvoiceDate BETWEEN ? AND ? AND PriceDeviationPct > 0
               AND Status IN (N'AutoApproved', N'Approved', N'NeedsReview')"""
    if supplier:
        sql += " AND VendorName LIKE ?"
        params.append(_like(supplier))
    sql += " GROUP BY VendorName, ProductName, Sku ORDER BY overpayment_eur DESC"
    return {"period": label, "rows": db.query(sql, tuple(params), persona=persona)}


SOURCE_FILTERS = {"live": "Source IN (N'stage', N'audience', N'cli')", "audience": "Source = N'audience'",
                  "stage": "Source = N'stage'", "legacy": "Source = N'legacy'", "all": "1 = 1"}


def get_invoice_processing_stats(persona: str, since_minutes=None, source: str = "live") -> dict[str, Any]:
    where = SOURCE_FILTERS.get(source, SOURCE_FILTERS["live"])
    params: list[Any] = []
    if since_minutes:
        where += " AND ReceivedAt >= DATEADD(minute, ?, SYSUTCDATETIME())"
        params.append(-int(since_minutes))
    by_status = db.query(f"""SELECT Status AS status, COUNT(*) AS invoices,
                                    CAST(AVG(CAST(ProcessingMs AS float)) / 1000 AS decimal(8,1)) AS avg_processing_seconds,
                                    SUM(TotalAmount) AS total_amount
                             FROM dbo.Invoices WHERE {where} GROUP BY Status ORDER BY invoices DESC""",
                         tuple(params), persona=persona)
    reasons = db.query(f"""SELECT TOP (5) LEFT(DecisionReason, 160) AS reason, COUNT(*) AS invoices
                           FROM dbo.Invoices WHERE {where} AND Status IN (N'NeedsReview', N'Rejected')
                           GROUP BY LEFT(DecisionReason, 160) ORDER BY invoices DESC""",
                       tuple(params), persona=persona)
    total = sum(r["invoices"] for r in by_status)
    auto = sum(r["invoices"] for r in by_status if r["status"] == "AutoApproved")
    return {"invoices": total, "auto_approval_rate_pct": round(100 * auto / total, 1) if total else None,
            "by_status": by_status, "top_review_reasons": reasons}


def find_products(persona: str, query: str | None = None) -> dict[str, Any]:
    params: list[Any] = []
    sql = """SELECT p.Sku AS sku, p.ProductName AS name, p.Category AS category, p.ListPrice AS list_price,
                    v.VendorName AS supplier
             FROM dbo.Products p JOIN dbo.Vendors v ON v.VendorId = p.PreferredVendorId"""
    if query:
        sql += " WHERE p.ProductName LIKE ? OR p.Sku LIKE ? OR p.Category LIKE ?"
        params.extend([_like(query)] * 3)
    return {"rows": db.query(sql + " ORDER BY p.Sku", tuple(params), persona=persona)}


TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_sales_summary": get_sales_summary,
    "get_margin_trend": get_margin_trend,
    "get_supplier_price_deviations": get_supplier_price_deviations,
    "get_invoice_processing_stats": get_invoice_processing_stats,
    "find_products": find_products,
}


def execute(name: str, arguments_json: str, persona: str) -> str:
    """Run one tool call from the agent and return JSON text for the function_call_output."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        args = json.loads(arguments_json or "{}")
        result = fn(persona, **args)
        if isinstance(result.get("rows"), list):
            result["rows"] = result["rows"][:MAX_ROWS]
            if not result["rows"]:
                result["note"] = "No rows. Either there is no data for this filter or this role can't see it."
        return json.dumps(db.to_json_safe(result))
    except Exception as ex:  # report errors to the model instead of failing the request
        return json.dumps({"error": str(ex)[:300]})
