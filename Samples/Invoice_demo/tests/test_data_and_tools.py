"""Seed data story, period handling of the sales tools, and the agent tool schemas."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

import demo_catalog as cat
import seed_data
from app import agent_definitions
from app.data_tools import resolve_period


def test_seed_is_deterministic_and_tells_the_story():
    a = seed_data.generate(date(2026, 9, 27))
    b = seed_data.generate(date(2026, 9, 27))
    assert [len(t.rows) for t in a.tables] == [len(t.rows) for t in b.tables]
    assert a.creep_start == date(2026, 7, 1)

    battery = cat.PRODUCT_BY_SKU[cat.PRICE_CREEP_SKU].product_id
    orders = {r[0]: r[2] for r in a.table("dbo.SalesOrders").rows}
    rev, cost = defaultdict(Decimal), defaultdict(Decimal)
    for so, _, pid, _, _, _, net, _, c in a.table("dbo.SalesOrderLines").rows:
        if pid == battery:
            m = orders[so].strftime("%Y-%m")
            rev[m] += net
            cost[m] += c
    margin = {m: (rev[m] - cost[m]) / rev[m] for m in rev}
    assert margin["2026-09"] < margin["2026-06"] - Decimal("0.05")  # at least 5 points lower

    demo_pos = [r for r in a.table("dbo.PurchaseOrders").rows if r[1].startswith("PO-DEMO")]
    assert len(demo_pos) == len(cat.SAMPLE_INVOICES)


def test_every_sample_invoice_matches_its_purchase_order():
    for s in cat.SAMPLE_INVOICES:
        for line in s.lines:
            p = cat.PRODUCT_BY_SKU[line.sku]
            assert p.vendor_code == s.vendor_code


def test_periods():
    as_of = date(2026, 9, 27)
    assert resolve_period("last_quarter", as_of)[:2] == (date(2026, 4, 1), date(2026, 6, 30))
    assert resolve_period("this_quarter", as_of)[:2] == (date(2026, 7, 1), as_of)
    assert resolve_period("last_month", as_of)[:2] == (date(2026, 8, 1), date(2026, 8, 31))
    assert resolve_period("year_to_date", as_of)[0] == date(2026, 1, 1)
    assert resolve_period("custom", as_of, "2026-01-01", "2026-03-31")[:2] == (date(2026, 1, 1), date(2026, 3, 31))
    assert resolve_period("last_quarter", date(2026, 2, 10))[:2] == (date(2025, 10, 1), date(2025, 12, 31))


def test_tool_schemas_are_strict_compatible():
    """Strict function calling: every property is required and no extra properties are allowed."""
    for tool in agent_definitions.TOOLS:
        params = tool["parameters"]
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"]), tool["name"]


def test_every_tool_has_an_implementation():
    from app import data_tools
    assert {t["name"] for t in agent_definitions.TOOLS} == set(data_tools.TOOL_FUNCTIONS)


def test_sql_literals():
    import common
    assert common.sql_literal("O'Brien") == "N'O''Brien'"
    assert common.sql_literal(Decimal("1.50")) == "1.50"
    assert common.sql_literal(None) == "NULL"
    assert common.split_batches("SELECT 1\nGO\nSELECT 2\n go \n") == ["SELECT 1", "SELECT 2"]
