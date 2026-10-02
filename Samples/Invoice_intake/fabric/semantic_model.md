# Semantic model "AlpenradSales" (Direct Lake on the lakehouse)

Create it from the lakehouse **AlpenradLH** (ribbon: **New semantic model**), select all nine tables:
`Regions, Customers, Vendors, Products, Calendar, Contracts, SalesLines, Invoices, InvoiceLines`.

## Relationships

Open the model in **Editing** mode → **Manage relationships** → **New relationship**. All are
many-to-one (`*:1`), single cross-filter direction, active.

| From (many) | Column | To (one) | Column |
|---|---|---|---|
| SalesLines | ProductId | Products | ProductId |
| SalesLines | CustomerId | Customers | CustomerId |
| SalesLines | RegionId | Regions | RegionId |
| SalesLines | OrderDateKey | Calendar | DateKey |
| InvoiceLines | InvoiceId | Invoices | InvoiceId |
| InvoiceLines | ProductId | Products | ProductId |
| Invoices | VendorId | Vendors | VendorId |
| Invoices | InvoiceDateKey | Calendar | DateKey |
| Contracts | ProductId | Products | ProductId |
| Contracts | VendorId | Vendors | VendorId |

Don't relate `Customers` to `Regions` or `Products` to `Vendors` (that would create two filter paths;
`Products[SupplierName]` already carries the supplier).

Mark `Calendar` as a date table (**Table tools → Mark as date table**, date column `CalendarDate`).

## Measures

Create them in the `SalesLines` and `InvoiceLines` tables (**New measure**). Add a description to each;
the data agent and Copilot read descriptions.

```DAX
Revenue = SUM ( SalesLines[Revenue] )
Purchase Cost = SUM ( SalesLines[CostAmount] )
Gross Margin = [Revenue] - [Purchase Cost]
Gross Margin % = DIVIDE ( [Gross Margin], [Revenue] )
Units Sold = SUM ( SalesLines[QuantitySold] )
Orders = DISTINCTCOUNT ( SalesLines[SalesOrderId] )
Avg Unit Cost = DIVIDE ( [Purchase Cost], [Units Sold] )
Revenue PY = CALCULATE ( [Revenue], SAMEPERIODLASTYEAR ( Calendar[CalendarDate] ) )
Revenue YoY % = DIVIDE ( [Revenue] - [Revenue PY], [Revenue PY] )
Gross Margin % PY = CALCULATE ( [Gross Margin %], SAMEPERIODLASTYEAR ( Calendar[CalendarDate] ) )

Invoiced Amount = SUM ( InvoiceLines[LineAmount] )
Overpayment vs Contract = SUM ( InvoiceLines[OverpaymentAmount] )
Avg Price Deviation % = DIVIDE ( AVERAGE ( InvoiceLines[PriceDeviationPct] ), 100 )
Invoices Received = DISTINCTCOUNT ( Invoices[InvoiceId] )
Invoices Auto-approved = CALCULATE ( [Invoices Received], Invoices[Status] = "AutoApproved" )
Invoices Needing Review = CALCULATE ( [Invoices Received], Invoices[Status] = "NeedsReview" )
Auto-approval Rate = DIVIDE ( [Invoices Auto-approved], CALCULATE ( [Invoices Received], Invoices[Source] <> "legacy" ) )
```

Format `Gross Margin %`, `Revenue YoY %`, `Avg Price Deviation %` and `Auto-approval Rate` as percentages,
the money measures as currency (EUR).

## Descriptions and synonyms (Prep data for AI)

On the model's **Prep data for AI** page (or in table/column properties) add short descriptions, for example:

| Object | Description |
|---|---|
| SalesLines | One row per product on a sales order to a dealer. Revenue is net of discount; CostAmount is the purchase cost at the time of sale. |
| Invoices | Supplier invoices. Status AutoApproved = approved by the AI intake; Approved = approved by a person; NeedsReview = waiting for a person. Source legacy = old manual process. |
| InvoiceLines | Lines of supplier invoices with the contract price and the deviation from it. |
| Products[SupplierName] | Synonyms: vendor, supplier |
| Regions[RegionName] | Values: DACH, Nordics, Benelux, Italy, UK & Ireland |

## Optional: row-level security roles (same idea as the web app personas)

**Manage roles** → new role:

| Role | Table | DAX filter |
|---|---|---|
| DACH Sales | Regions | `[RegionCode] = "DACH"` |
| DACH Sales | Invoices | `FALSE()` |
| Procurement | SalesLines | `FALSE()` |

Test with **View as**. Assign people to roles in the model's **Security** settings. The data agent uses the
signed-in user's identity, so RLS applies to its answers too.
