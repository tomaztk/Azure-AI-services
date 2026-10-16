"""Generates deterministic synthetic data for the demo database.

About 18 months of sales and purchasing history ending on the seed date ("as of"):
  - ~5,000 sales orders to ~50 dealers in 5 regions
  - one purchase order + goods receipt + supplier invoice per vendor and month
  - the story: from three months before the seed date, Voltaris Energy invoices the
    500Wh battery pack 6 %, 10 %, then 14 % above contract. Those invoices were approved
    manually ("legacy" process), so the margin on that product quietly dropped.
  - five open "demo" purchase orders (PO-DEMO-1001..1005) that the printable sample
    invoices refer to.

Run `python scripts/seed_data.py` to print a summary without touching a database.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

import demo_catalog as cat

SEASONALITY = {1: 0.70, 2: 0.80, 3: 1.05, 4: 1.20, 5: 1.30, 6: 1.25,
               7: 1.10, 8: 1.00, 9: 0.95, 10: 0.85, 11: 0.75, 12: 0.80}
BASE_ORDERS_PER_MONTH = 260
HISTORY_MONTHS = 18
CENT = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Table:
    name: str
    columns: list[str]
    rows: list[tuple] = field(default_factory=list)
    identity_insert: bool = False


@dataclass
class SeedData:
    as_of: date
    creep_start: date
    tables: list[Table]

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)


def generate(as_of: date | None = None, seed: int = 42) -> SeedData:
    as_of = as_of or date.today()
    rng = random.Random(seed)
    current_month = cat.month_start(as_of)
    start = cat.add_months(current_month, -(HISTORY_MONTHS - 1))
    creep_start = cat.add_months(current_month, -2)
    calendar_end = date(as_of.year + 1, 12, 31)

    # ---------------- master data ----------------
    regions = Table("dbo.Regions", ["RegionId", "RegionCode", "RegionName"], list(cat.REGIONS))

    vendors = Table("dbo.Vendors", ["VendorId", "VendorCode", "VendorName", "Street", "City", "Country",
                                    "CountryCode", "VatId", "Iban", "PaymentTermDays"])
    for v in cat.VENDORS:
        vendors.rows.append((v.vendor_id, v.code, v.name, v.street, v.city, v.country, v.country_code,
                             v.vat_id, v.iban, v.payment_term_days))

    products = Table("dbo.Products", ["ProductId", "Sku", "ProductName", "Category", "ListPrice", "PreferredVendorId"])
    for p in cat.PRODUCTS:
        products.rows.append((p.product_id, p.sku, p.name, p.category, p.list_price,
                              cat.VENDOR_BY_CODE[p.vendor_code].vendor_id))

    contracts = Table("dbo.Contracts", ["ContractId", "ContractNumber", "VendorId", "ProductId", "UnitPrice",
                                        "Currency", "ValidFrom", "ValidTo", "MaxPriceDeviationPct"])
    for i, p in enumerate(cat.PRODUCTS, start=1):
        v = cat.VENDOR_BY_CODE[p.vendor_code]
        contracts.rows.append((i, f"C-{v.code}-{p.sku[-3:]}", v.vendor_id, p.product_id, p.contract_price,
                               "EUR", date(start.year - 1, 1, 1), calendar_end, cat.MAX_PRICE_DEVIATION_PCT))

    customers = Table("dbo.Customers", ["CustomerId", "CustomerName", "City", "Country", "RegionId", "Segment"])
    customer_weights: dict[int, list[tuple[int, float, str]]] = defaultdict(list)
    cid = 0
    used_names = set()
    for region_id, countries in cat.REGION_CITIES.items():
        for country, cities in countries:
            for city in cities:
                for _ in range(2 if region_id == 1 else 1 + (rng.random() < 0.5)):
                    prefix = rng.choice(cat.CUSTOMER_PREFIXES)
                    name = f"{prefix} {city}"
                    while name in used_names:
                        prefix = rng.choice(cat.CUSTOMER_PREFIXES)
                        name = f"{prefix} {city}"
                    used_names.add(name)
                    cid += 1
                    segment = rng.choices(["Dealer", "Key account", "Online"], [0.75, 0.12, 0.13])[0]
                    size = {"Dealer": 1.0, "Key account": 3.0, "Online": 1.6}[segment] * rng.uniform(0.6, 1.4)
                    customers.rows.append((cid, name, city, country, region_id, segment))
                    customer_weights[region_id].append((cid, size, segment))

    calendar = Table("dbo.Calendar", ["DateKey", "Date", "Year", "Quarter", "QuarterName", "Month", "MonthName", "YearMonth"])
    d = start
    while d <= calendar_end:
        q = (d.month - 1) // 3 + 1
        calendar.rows.append((int(d.strftime("%Y%m%d")), d, d.year, q, f"{d.year}-Q{q}", d.month,
                              d.strftime("%B"), d.strftime("%Y-%m")))
        d += timedelta(days=1)

    # ---------------- sales ----------------
    sales_orders = Table("dbo.SalesOrders", ["SalesOrderId", "OrderNumber", "OrderDate", "CustomerId", "RegionId", "Channel"])
    sales_lines = Table("dbo.SalesOrderLines", ["SalesOrderId", "LineNumber", "ProductId", "Quantity", "UnitPrice",
                                                "DiscountPct", "NetAmount", "UnitCost", "CostAmount"])
    monthly_qty: dict[tuple[date, int], int] = defaultdict(int)
    region_ids = list(cat.REGION_WEIGHTS)
    region_w = [cat.REGION_WEIGHTS[r] for r in region_ids]
    prod_w = [p.popularity for p in cat.PRODUCTS]
    so_id = 0
    month = start
    month_index = 0
    while month <= current_month:
        last_day = (cat.add_months(month, 1) - timedelta(days=1)).day
        if month == current_month:
            last_day = as_of.day
        n_orders = round(BASE_ORDERS_PER_MONTH * SEASONALITY[month.month] * (1 + 0.01 * month_index)
                         * rng.uniform(0.95, 1.05) * last_day / ((cat.add_months(month, 1) - timedelta(days=1)).day))
        seq = 0
        for _ in range(n_orders):
            so_id += 1
            seq += 1
            order_date = month.replace(day=rng.randint(1, last_day))
            region = rng.choices(region_ids, region_w)[0]
            cust_id, _, segment = rng.choices(customer_weights[region], [w for _, w, _ in customer_weights[region]])[0]
            channel = rng.choices(["Dealer portal", "Field sales", "Phone"], [0.6, 0.3, 0.1])[0]
            sales_orders.rows.append((so_id, f"SO-{month:%Y%m}-{seq:05d}", order_date, cust_id, region, channel))
            n_lines = rng.choice([1, 2, 2, 3, 3, 4])
            chosen: list[cat.Product] = []
            while len(chosen) < n_lines:
                p = rng.choices(cat.PRODUCTS, prod_w)[0]
                if p not in chosen:
                    chosen.append(p)
            for ln, p in enumerate(chosen, start=1):
                qty = rng.randint(*p.qty_range)
                if segment == "Key account":
                    qty = math.ceil(qty * 1.8)
                disc = Decimal({"Dealer": rng.choice([3, 4, 5, 6, 8]),
                                "Key account": rng.choice([10, 12, 14, 15]),
                                "Online": rng.choice([0, 0, 2, 3])}[segment])
                net = money(Decimal(qty) * p.list_price * (1 - disc / 100))
                unit_cost = cat.unit_cost_for_month(p, month, creep_start)
                sales_lines.rows.append((so_id, ln, p.product_id, qty, p.list_price, disc, net,
                                         unit_cost, money(Decimal(qty) * unit_cost)))
                monthly_qty[(month, p.product_id)] += qty
        month = cat.add_months(month, 1)
        month_index += 1

    # ---------------- purchasing (legacy, pre-AI) ----------------
    pos = Table("dbo.PurchaseOrders", ["PurchaseOrderId", "PONumber", "VendorId", "OrderDate", "Status", "Currency", "TotalAmount"])
    po_lines = Table("dbo.PurchaseOrderLines", ["PurchaseOrderId", "LineNumber", "ProductId", "Quantity", "UnitPrice"])
    receipts = Table("dbo.GoodsReceipts", ["GoodsReceiptId", "PurchaseOrderId", "ProductId", "ReceivedQuantity", "ReceivedDate"])
    invoices = Table("dbo.Invoices", ["InvoiceId", "InvoiceNumber", "VendorId", "VendorNameRaw", "PONumber", "PurchaseOrderId",
                                      "InvoiceDate", "DueDate", "Currency", "SubtotalAmount", "TaxAmount", "TotalAmount",
                                      "Status", "ProcessingStage", "DecisionType", "DecisionReason", "MaxPriceDeviationPct",
                                      "Source", "ReceivedAt", "DecidedAt", "DecidedBy"], identity_insert=True)
    inv_lines = Table("dbo.InvoiceLines", ["InvoiceId", "LineNumber", "ProductId", "Sku", "Description", "Quantity",
                                           "UnitPrice", "LineAmount", "ContractUnitPrice", "PriceDeviationPct"])
    approval_log = Table("dbo.ApprovalLog", ["InvoiceId", "Action", "Actor", "Comment", "CreatedAt"])

    po_id = gr_id = inv_id = 0
    month = start
    while month <= current_month:
        for v in cat.VENDORS:
            vendor_products = [p for p in cat.PRODUCTS if p.vendor_code == v.code]
            order_date = month + timedelta(days=2)
            if order_date > as_of:
                continue
            po_id += 1
            po_number = f"PO-{month:%Y%m}-{v.code}"
            lines = []
            for p in vendor_products:
                qty = monthly_qty.get((month, p.product_id), 0)
                qty = max(5, int(math.ceil(qty * 1.05 / 5.0)) * 5)
                lines.append((p, qty))
            po_total = sum(money(Decimal(q) * p.contract_price) for p, q in lines)
            received_date = order_date + timedelta(days=5)
            invoice_date = order_date + timedelta(days=7)
            received = received_date <= as_of
            invoiced = invoice_date < as_of
            status = "Invoiced" if invoiced else ("Received" if received else "Open")
            pos.rows.append((po_id, po_number, v.vendor_id, order_date, status, "EUR", po_total))
            for ln, (p, q) in enumerate(lines, start=1):
                po_lines.rows.append((po_id, ln, p.product_id, Decimal(q), p.contract_price))
                if received:
                    gr_id += 1
                    receipts.rows.append((gr_id, po_id, p.product_id, Decimal(q), received_date))
            if not invoiced:
                continue
            inv_id += 1
            subtotal = Decimal("0")
            max_dev = Decimal("0")
            for ln, (p, q) in enumerate(lines, start=1):
                unit = cat.unit_cost_for_month(p, month, creep_start)
                amount = money(Decimal(q) * unit)
                subtotal += amount
                dev = money((unit - p.contract_price) / p.contract_price * 100)
                max_dev = max(max_dev, dev)
                inv_lines.rows.append((inv_id, ln, p.product_id, p.sku, p.name, Decimal(q), unit, amount,
                                       p.contract_price, dev))
            tax = money(subtotal * v.vat_rate)
            received_at = datetime.combine(invoice_date, time(8, 15))
            decided_at = datetime.combine(invoice_date + timedelta(days=2), time(10, 30))
            invoices.rows.append((inv_id, f"{v.invoice_prefix}-{month:%Y%m}-{rng.randint(1000, 9999)}", v.vendor_id, v.name,
                                  po_number, po_id, invoice_date, invoice_date + timedelta(days=v.payment_term_days),
                                  "EUR", subtotal, tax, subtotal + tax, "Approved", "done", "Legacy",
                                  "Approved manually in the old AP process (no automated checks).", max_dev,
                                  "legacy", received_at, decided_at, "AP clerk (manual)"))
            approval_log.rows.append((inv_id, "Approved", "AP clerk (manual)", "Legacy approval", decided_at))
        month = cat.add_months(month, 1)

    # ---------------- open demo purchase orders for the sample invoices ----------------
    demo_order_date, demo_receipt_date = cat.demo_po_dates(as_of)
    for s in cat.SAMPLE_INVOICES:
        v = cat.VENDOR_BY_CODE[s.vendor_code]
        po_id += 1
        total = sum(money(Decimal(l.quantity) * cat.PRODUCT_BY_SKU[l.sku].contract_price) for l in s.lines)
        pos.rows.append((po_id, s.po_number, v.vendor_id, demo_order_date, "Received", "EUR", total))
        for ln, l in enumerate(s.lines, start=1):
            p = cat.PRODUCT_BY_SKU[l.sku]
            po_lines.rows.append((po_id, ln, p.product_id, Decimal(l.quantity), p.contract_price))
            gr_id += 1
            receipts.rows.append((gr_id, po_id, p.product_id, Decimal(l.quantity), demo_receipt_date))

    tables = [regions, vendors, products, contracts, customers, calendar, pos, po_lines, receipts,
              invoices, inv_lines, approval_log, sales_orders, sales_lines]
    return SeedData(as_of=as_of, creep_start=creep_start, tables=tables)


# Tables in delete order (children first) for a reseed.
DELETE_ORDER = ["dbo.ApprovalLog", "dbo.InvoiceLines", "dbo.Invoices", "dbo.GoodsReceipts", "dbo.PurchaseOrderLines",
                "dbo.PurchaseOrders", "dbo.SalesOrderLines", "dbo.SalesOrders", "dbo.AudienceQuestions",
                "dbo.Contracts", "dbo.Customers", "dbo.Products", "dbo.Vendors", "dbo.Calendar", "dbo.Regions"]


def summary(data: SeedData) -> str:
    """Human-readable check of the story in the generated data."""
    lines = [f"as of {data.as_of}, price creep from {data.creep_start}"]
    for t in data.tables:
        lines.append(f"  {t.name:<24} {len(t.rows):>7} rows")
    orders = {r[0]: r[2] for r in data.table("dbo.SalesOrders").rows}
    by_month: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    battery = cat.PRODUCT_BY_SKU[cat.PRICE_CREEP_SKU].product_id
    for so, _, pid, qty, _, _, net, _, cost in data.table("dbo.SalesOrderLines").rows:
        if pid == battery:
            key = orders[so].strftime("%Y-%m")
            by_month[key][0] += net
            by_month[key][1] += cost
    lines.append(f"  gross margin of {cat.PRICE_CREEP_SKU} by month:")
    for key in sorted(by_month)[-6:]:
        rev, cost = by_month[key]
        lines.append(f"    {key}: revenue {rev:>12,.2f}  margin {(rev - cost) / rev * 100:5.1f} %")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary(generate()))
