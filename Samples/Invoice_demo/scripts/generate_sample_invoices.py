"""Renders the printable sample invoices (samples/*.pdf) that match the demo purchase orders.

    python scripts/generate_sample_invoices.py            # invoice date = today
    python scripts/generate_sample_invoices.py --date 2026-10-14

Also writes samples/all_invoices_handout.pdf (one invoice per page, for printing) and,
when WEB_APP_URL is known, samples/audience_qr.png for your slides.
Regenerate on the day of the session so invoice numbers and dates are fresh.
"""
from __future__ import annotations

import argparse
import math
import os
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import common as c
import demo_catalog as cat

W, H = 1654, 2339  # A4 at 200 dpi
MARGIN = 120
INK = (28, 28, 30)
GREY = (110, 110, 115)
LIGHT = (225, 225, 228)

FONT_CANDIDATES = ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc", "LiberationSans-Regular.ttf",
                   "/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def font(size: int, candidates: list[str] = FONT_CANDIDATES) -> ImageFont.FreeTypeFont:
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def money(v: Decimal) -> str:
    return f"{v:,.2f}"


def text(d: ImageDraw.ImageDraw, xy, s, size=30, fill=INK, bold=False, anchor="la", candidates=FONT_CANDIDATES):
    d.text(xy, s, font=font(size, candidates), fill=fill, anchor=anchor,
           stroke_width=1 if bold else 0, stroke_fill=fill)


def render(sample: cat.SampleInvoice, invoice_date: date, number: str) -> Image.Image:
    v = cat.VENDOR_BY_CODE[sample.vendor_code]
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Vendor block
    y = MARGIN
    d.rectangle([MARGIN, y, MARGIN + 14, y + 110], fill=(31, 95, 139))
    text(d, (MARGIN + 40, y), v.name, 50, bold=True)
    text(d, (MARGIN + 40, y + 64), f"{v.street} · {v.city} · {v.country}", 26, GREY)
    text(d, (MARGIN + 40, y + 98), f"VAT ID {v.vat_id}", 26, GREY)
    text(d, (W - MARGIN, y), "INVOICE", 72, bold=True, anchor="ra")

    # Bill to + invoice facts
    y = 380
    text(d, (MARGIN, y), "Bill to", 26, GREY)
    b = cat.BUYER
    for i, line in enumerate([b["name"], b["street"], f'{b["city"]}, {b["country"]}', f'VAT ID {b["vat_id"]}']):
        text(d, (MARGIN, y + 40 + i * 40), line, 32, bold=(i == 0))
    facts = [("Invoice number", number), ("Invoice date", invoice_date.isoformat()),
             ("Due date", (invoice_date + timedelta(days=v.payment_term_days)).isoformat())]
    if sample.print_po_number:
        facts.append(("Purchase order", sample.po_number))
    facts.append(("Customer number", "K-10442"))
    fx = W - MARGIN - 640
    for i, (k, val) in enumerate(facts):
        yy = y + 40 + i * 46
        text(d, (fx, yy), k, 30, GREY)
        text(d, (W - MARGIN, yy), val, 30, bold=True, anchor="ra")

    # Line items
    y = 720
    x_pos, x_sku, x_desc = MARGIN + 16, MARGIN + 90, MARGIN + 330      # left-aligned columns
    x_qty, x_unit, x_amt = W - MARGIN - 560, W - MARGIN - 290, W - MARGIN - 16  # right edges
    d.rectangle([MARGIN, y, W - MARGIN, y + 60], fill=(240, 241, 244))
    heads = [("Pos", x_pos, "la"), ("Item no.", x_sku, "la"), ("Description", x_desc, "la"),
             ("Qty", x_qty, "ra"), ("Unit price", x_unit, "ra"), ("Amount EUR", x_amt, "ra")]
    for h, x, a in heads:
        text(d, (x, y + 16), h, 28, bold=True, anchor=a)
    y += 60
    subtotal = Decimal("0")
    for i, line in enumerate(sample.lines, start=1):
        p = cat.PRODUCT_BY_SKU[line.sku]
        price = line.invoice_unit_price or p.contract_price
        qty = line.invoice_quantity or line.quantity
        amount = (price * qty).quantize(Decimal("0.01"))
        subtotal += amount
        row = [(str(i), x_pos, "la"), (p.sku, x_sku, "la"), (p.name, x_desc, "la"),
               (f"{qty} pcs", x_qty, "ra"), (money(price), x_unit, "ra"),
               (money(amount), x_amt, "ra")]
        for s, x, a in row:
            text(d, (x, y + 22), s, 30, anchor=a)
        y += 76
        d.line([MARGIN, y, W - MARGIN, y], fill=LIGHT, width=2)

    # Totals
    tax = (subtotal * v.vat_rate).quantize(Decimal("0.01"))
    total = subtotal + tax
    y += 40
    tx = W - MARGIN - 640
    vat_label = f"VAT {int(v.vat_rate * 100)} %" if v.vat_rate else "VAT 0 % (reverse charge)"
    for k, val, bold in [("Subtotal", money(subtotal), False), (vat_label, money(tax), False)]:
        text(d, (tx, y), k, 32, GREY)
        text(d, (W - MARGIN, y), val, 32, bold=bold, anchor="ra")
        y += 52
    d.line([tx, y, W - MARGIN, y], fill=INK, width=3)
    y += 18
    text(d, (tx, y), "Total EUR", 40, bold=True)
    total_xy = (W - MARGIN, y)
    text(d, total_xy, money(total), 40, bold=True, anchor="ra")
    if not v.vat_rate:
        text(d, (MARGIN, y + 8), "Reverse charge: VAT to be accounted for by the recipient.", 24, GREY)

    # Payment and notes
    y = 1850
    d.line([MARGIN, y, W - MARGIN, y], fill=LIGHT, width=2)
    text(d, (MARGIN, y + 30), "Payment", 28, bold=True)
    text(d, (MARGIN, y + 72), f"Please transfer within {v.payment_term_days} days to IBAN {v.iban}", 28)
    text(d, (MARGIN, y + 112), f"Reference: {number}", 28)
    text(d, (W // 2, H - 90), f"{v.name} · {v.city} · FICTIONAL COMPANY - SAMPLE INVOICE FOR A LIVE DEMO",
         22, GREY, anchor="ma")

    if sample.poor_scan:
        img = poor_scan(img)
    return img


def poor_scan(img: Image.Image) -> Image.Image:
    """Make the page look like a slightly crooked, noisy phone scan."""
    rng = random.Random(4)
    img = img.rotate(1.2, resample=Image.BICUBIC, expand=False, fillcolor=(236, 234, 228))
    img = img.filter(ImageFilter.GaussianBlur(0.9))
    px = img.load()
    for _ in range(90000):
        x, y = rng.randrange(W), rng.randrange(H)
        g = rng.randint(150, 230)
        px[x, y] = (g, g, g)
    # uneven lighting
    shade = Image.new("L", (W, H))
    sd = ImageDraw.Draw(shade)
    for i in range(H):
        sd.line([0, i, W, i], fill=int(18 * math.sin(i / H * math.pi)))
    return Image.composite(Image.new("RGB", (W, H), (200, 196, 188)), img, shade)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="invoice date (default today)")
    args = parser.parse_args()
    c.load_env()
    c.step("Sample invoices")
    out = c.SAMPLES_DIR
    out.mkdir(exist_ok=True)
    pages = []
    for i, s in enumerate(cat.SAMPLE_INVOICES, start=1):
        v = cat.VENDOR_BY_CODE[s.vendor_code]
        number = f"{v.invoice_prefix}-{args.date:%y%m%d}-{i:02d}"
        img = render(s, args.date, number)
        path = out / f"{s.file_stem}.pdf"
        img.save(path, "PDF", resolution=200.0)
        img.convert("RGB").save(out / f"{s.file_stem}.jpg", "JPEG", quality=88)
        pages.append(img)
        c.ok(f"{path.name:<42} {s.title} -> expected: {s.expected}")
    pages[0].save(out / "all_invoices_handout.pdf", "PDF", resolution=200.0, save_all=True, append_images=pages[1:])
    c.ok("all_invoices_handout.pdf (print a stack of these for the audience)")

    url = os.environ.get("WEB_APP_URL")
    if url:
        import qrcode
        qrcode.make(url, box_size=16, border=2).save(out / "audience_qr.png")
        c.ok(f"audience_qr.png -> {url}")


if __name__ == "__main__":
    main()
