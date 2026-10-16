"""Master data for the fictional wholesaler "Alpenrad Handels GmbH" (Vienna).

Single source of truth for the seed script and the printable sample invoices,
so the invoices people scan always match a purchase order and a contract in the database.
All companies, VAT IDs and IBANs are invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

BUYER = {
    "name": "Alpenrad Handels GmbH",
    "street": "Donaustraße 17",
    "city": "1020 Wien",
    "country": "Austria",
    "vat_id": "ATU99000001",
}

REGIONS = [
    # RegionId, code, name
    (1, "DACH", "DACH"),
    (2, "NORD", "Nordics"),
    (3, "BNLX", "Benelux"),
    (4, "ITA", "Italy"),
    (5, "UKI", "UK & Ireland"),
]

# Region -> list of (country, [cities])
REGION_CITIES = {
    1: [("Austria", ["Wien", "Graz", "Linz", "Salzburg", "Innsbruck"]),
        ("Germany", ["München", "Stuttgart", "Köln", "Hamburg", "Freiburg"]),
        ("Switzerland", ["Zürich", "Bern", "Basel"])],
    2: [("Sweden", ["Stockholm", "Malmö"]), ("Denmark", ["København", "Aarhus"]),
        ("Norway", ["Oslo"]), ("Finland", ["Helsinki"])],
    3: [("Netherlands", ["Amsterdam", "Utrecht", "Rotterdam"]), ("Belgium", ["Antwerpen", "Gent"]),
        ("Luxembourg", ["Luxembourg"])],
    4: [("Italy", ["Milano", "Torino", "Bologna", "Verona", "Bolzano"])],
    5: [("United Kingdom", ["London", "Bristol", "Manchester", "Edinburgh"]), ("Ireland", ["Dublin"])],
}

# Share of order volume per region
REGION_WEIGHTS = {1: 0.40, 2: 0.15, 3: 0.15, 4: 0.15, 5: 0.15}

CUSTOMER_PREFIXES = ["Radwerk", "Velo Point", "E-Bike Center", "Cycle Hub", "Pedal & Co",
                     "Bike Loft", "Trail Shop", "Stadtrad", "Spoke House", "Kettenblatt"]


@dataclass(frozen=True)
class Vendor:
    vendor_id: int
    code: str
    name: str
    street: str
    city: str
    country: str
    country_code: str
    vat_id: str
    iban: str
    payment_term_days: int
    invoice_prefix: str

    @property
    def vat_rate(self) -> Decimal:
        # Austrian suppliers charge 20 % VAT; EU suppliers invoice with reverse charge.
        return Decimal("0.20") if self.country_code == "AT" else Decimal("0.00")


VENDORS = [
    Vendor(1, "V001", "Brennerwerk Metall GmbH", "Gewerbepark 4", "6020 Innsbruck", "Austria", "AT",
           "ATU99100001", "AT61 1904 3002 3457 3201", 30, "BW"),
    Vendor(2, "V002", "Voltaris Energy AG", "Industriestraße 88", "70565 Stuttgart", "Germany", "DE",
           "DE999200002", "DE89 3704 0044 0532 0130 00", 30, "VOL"),
    Vendor(3, "V003", "Tauern Drive Systems GmbH", "Alpenstraße 12", "5020 Salzburg", "Austria", "AT",
           "ATU99300003", "AT48 3200 0000 1234 5864", 45, "TDS"),
    Vendor(4, "V004", "Lago Components S.r.l.", "Via dell'Industria 21", "25125 Brescia", "Italy", "IT",
           "IT99900000004", "IT60 X054 2811 1010 0000 0123 456", 60, "LGC"),
    Vendor(5, "V005", "Nordkap Safety AB", "Hamngatan 3", "411 06 Göteborg", "Sweden", "SE",
           "SE999900000501", "SE45 5000 0000 0583 9825 7466", 30, "NKS"),
]
VENDOR_BY_CODE = {v.code: v for v in VENDORS}
VENDOR_BY_ID = {v.vendor_id: v for v in VENDORS}


@dataclass(frozen=True)
class Product:
    product_id: int
    sku: str
    name: str
    category: str
    list_price: Decimal     # selling price
    vendor_code: str
    contract_price: Decimal  # agreed purchase price
    popularity: float        # relative order frequency
    qty_range: tuple[int, int]


PRODUCTS = [
    Product(1, "AR-FRM-100", "Trail Frame Alu 29in", "Frames", Decimal("349.00"), "V001", Decimal("189.00"), 0.9, (2, 8)),
    Product(2, "AR-FRM-200", "City Frame Step-Through", "Frames", Decimal("299.00"), "V001", Decimal("162.00"), 0.8, (2, 8)),
    Product(3, "AR-BAT-500", "Battery Pack 500Wh", "Batteries", Decimal("529.00"), "V002", Decimal("312.00"), 1.2, (2, 10)),
    Product(4, "AR-BAT-750", "Battery Pack 750Wh", "Batteries", Decimal("699.00"), "V002", Decimal("418.00"), 0.6, (1, 6)),
    Product(5, "AR-CHG-004", "Fast Charger 4A", "Chargers", Decimal("89.00"), "V002", Decimal("41.50"), 0.7, (3, 15)),
    Product(6, "AR-MOT-250", "Mid-Drive Motor 250W", "Motors", Decimal("459.00"), "V003", Decimal("268.00"), 0.8, (1, 6)),
    Product(7, "AR-DSP-010", "Handlebar Display", "Electronics", Decimal("119.00"), "V003", Decimal("58.00"), 0.7, (2, 12)),
    Product(8, "AR-BRK-HYD", "Hydraulic Disc Brake Set", "Brakes", Decimal("149.00"), "V004", Decimal("74.00"), 1.0, (2, 12)),
    Product(9, "AR-TIR-29T", "Trail Tire 29x2.4", "Tires", Decimal("54.00"), "V004", Decimal("23.50"), 1.1, (6, 40)),
    Product(10, "AR-HLM-CTY", "City Helmet MIPS", "Safety", Decimal("89.00"), "V005", Decimal("38.00"), 0.9, (3, 20)),
    Product(11, "AR-LGT-SET", "Light Set 80 lux", "Safety", Decimal("69.00"), "V005", Decimal("27.50"), 0.8, (3, 20)),
]
PRODUCT_BY_SKU = {p.sku: p for p in PRODUCTS}
PRODUCT_BY_ID = {p.product_id: p for p in PRODUCTS}

MAX_PRICE_DEVIATION_PCT = Decimal("2.00")

# The story: Voltaris quietly raises the price of the 500Wh battery pack,
# starting three months before the seed date. Nobody catches it in the old manual process.
PRICE_CREEP_SKU = "AR-BAT-500"
PRICE_CREEP_STEPS = [Decimal("1.06"), Decimal("1.10"), Decimal("1.14")]  # month 1, 2, 3+


@dataclass(frozen=True)
class DemoPoLine:
    sku: str
    quantity: int                              # ordered and received (purchase order + goods receipt)
    invoice_unit_price: Decimal | None = None  # None = contract price
    invoice_quantity: int | None = None        # None = the quantity received


@dataclass(frozen=True)
class SampleInvoice:
    """A printable invoice for the stage / the audience, tied to a demo purchase order."""
    file_stem: str
    title: str
    expected: str
    vendor_code: str
    po_number: str
    lines: list[DemoPoLine] = field(default_factory=list)
    print_po_number: bool = True
    poor_scan: bool = False                    # render as a crooked, noisy phone scan


SAMPLE_INVOICES = [
    SampleInvoice("01_clean_brennerwerk", "Clean invoice", "Auto-approved",
                  "V001", "PO-DEMO-1001", [DemoPoLine("AR-FRM-100", 12)]),
    SampleInvoice("02_price_above_contract_voltaris", "Price 12% above contract", "Needs review: price deviation",
                  "V002", "PO-DEMO-1002", [DemoPoLine("AR-BAT-500", 10, Decimal("349.44"))]),
    SampleInvoice("03_missing_po_lago", "Missing PO number", "Needs review: no purchase order",
                  "V004", "PO-DEMO-1003", [DemoPoLine("AR-BRK-HYD", 20), DemoPoLine("AR-TIR-29T", 40)],
                  print_po_number=False),
    SampleInvoice("04_more_than_received_tauern", "Poor scan, 6 motors billed but 4 received",
                  "Needs review: more invoiced than received",
                  "V003", "PO-DEMO-1004", [DemoPoLine("AR-DSP-010", 15), DemoPoLine("AR-MOT-250", 4, invoice_quantity=6)],
                  poor_scan=True),
    SampleInvoice("05_clean_nordkap", "Clean invoice", "Auto-approved",
                  "V005", "PO-DEMO-1005", [DemoPoLine("AR-HLM-CTY", 30), DemoPoLine("AR-LGT-SET", 25)]),
]


def demo_po_dates(as_of: date) -> tuple[date, date]:
    """Order and goods-receipt dates of the demo purchase orders."""
    return as_of - timedelta(days=10), as_of - timedelta(days=4)


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, 1)


def unit_cost_for_month(product: Product, month: date, creep_start: date) -> Decimal:
    """Purchase price actually invoiced in a month (contract price, except for the price creep)."""
    price = product.contract_price
    if product.sku == PRICE_CREEP_SKU and month >= creep_start:
        step = (month.year - creep_start.year) * 12 + month.month - creep_start.month
        factor = PRICE_CREEP_STEPS[min(step, len(PRICE_CREEP_STEPS) - 1)]
        price = (price * factor).quantize(Decimal("0.01"))
    return price
