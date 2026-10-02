# Fabric data agent "AlpenradDataAgent"

Data sources (add in this order):

1. **AlpenradOntology** (ontology, Fabric IQ): business concepts and relationships
2. **AlpenradSales** (semantic model): measures such as Revenue, Gross Margin %, Overpayment vs Contract
3. **invoicedemo** (mirrored database): live rows, seconds behind Azure SQL. In the Explorer tick
   `Invoices, InvoiceLines, Vendors, Products, SalesOrders, SalesOrderLines, Regions, Customers, Contracts, Calendar`.

## Agent instructions

Paste into **Agent instructions**:

```text
You answer questions for Alpenrad Handels GmbH, a fictional e-bike parts wholesaler in Vienna.

Which source to use:
- Sales, revenue, gross margin, units, customers, regions, products, trends over months:
  use the semantic model AlpenradSales (measures Revenue, Gross Margin, Gross Margin %, Units Sold,
  Revenue YoY %) or the ontology AlpenradOntology.
- Supplier prices, contracts and overpayment over time: AlpenradSales (Overpayment vs Contract,
  Avg Price Deviation %) or the ontology.
- Anything about invoices processed today, in the last minutes or hours, "just approved", "the audience",
  "this session", or the current status of an invoice: use the mirrored database invoicedemo,
  because it is updated within seconds. The lakehouse behind the semantic model and ontology refreshes
  every 15 minutes.

Business vocabulary:
- Gross margin = revenue - purchase cost. Purchase cost comes from approved supplier invoices.
- Approved invoices: Status 'AutoApproved' (approved by the AI intake) or 'Approved' (by a person).
  'NeedsReview' = waiting for a person. Source 'legacy' = the old manual process; 'stage', 'audience'
  and 'cli' = the new AI intake.
- Price deviation = invoice unit price compared with the contract price, in percent.
- Regions: DACH, Nordics, Benelux, Italy, UK & Ireland. Currency is EUR.

Answer briefly (2-5 sentences or a small table). Mention the period you used.
Support group by in GQL.
```

## Data source instructions (mirrored database)

```text
Tables are in schema dbo. Sales revenue is SalesOrderLines.NetAmount, cost is SalesOrderLines.CostAmount.
Join SalesOrderLines to SalesOrders on SalesOrderId for OrderDate, CustomerId and RegionId.
Invoices.ReceivedAt and DecidedAt are UTC. Use GETUTCDATE() for "last N minutes/hours".
```

## Example queries (mirrored database)

Add under **Example queries → invoicedemo**. Semantic models and ontologies don't take example queries.

**Which invoices were approved in the last hour?**
```sql
SELECT TOP 20 i.InvoiceId, i.InvoiceNumber, v.VendorName, i.TotalAmount, i.Status, i.DecisionType, i.Source, i.DecidedAt
FROM dbo.Invoices AS i
LEFT JOIN dbo.Vendors AS v ON v.VendorId = i.VendorId
WHERE i.Status IN ('AutoApproved', 'Approved')
  AND i.ReceivedAt >= DATEADD(hour, -1, GETUTCDATE())
ORDER BY i.InvoiceId DESC;
```

**How many invoices did the audience scan, and how many needed a human?**
```sql
SELECT Status, COUNT(*) AS Invoices
FROM dbo.Invoices
WHERE Source = 'audience'
GROUP BY Status
ORDER BY Invoices DESC;
```

**Which suppliers invoice above contract price this quarter?**
```sql
SELECT v.VendorName, p.ProductName,
       COUNT(DISTINCT i.InvoiceId) AS Invoices,
       AVG(il.PriceDeviationPct) AS AvgDeviationPct,
       SUM(il.Quantity * (il.UnitPrice - il.ContractUnitPrice)) AS OverpaymentEUR
FROM dbo.InvoiceLines AS il
JOIN dbo.Invoices AS i ON i.InvoiceId = il.InvoiceId
JOIN dbo.Vendors AS v ON v.VendorId = i.VendorId
JOIN dbo.Products AS p ON p.ProductId = il.ProductId
WHERE il.PriceDeviationPct > 0
  AND i.Status IN ('AutoApproved', 'Approved', 'NeedsReview')
  AND i.InvoiceDate >= DATEFROMPARTS(YEAR(GETDATE()), (DATEPART(quarter, GETDATE()) - 1) * 3 + 1, 1)
GROUP BY v.VendorName, p.ProductName
ORDER BY OverpaymentEUR DESC;
```

**How did gross margin of the 500Wh battery pack develop over the last six months?**
```sql
SELECT LEFT(CONVERT(varchar(10), so.OrderDate, 23), 7) AS YearMonth,
       SUM(sol.NetAmount) AS Revenue,
       SUM(sol.NetAmount - sol.CostAmount) AS GrossMargin,
       100.0 * SUM(sol.NetAmount - sol.CostAmount) / SUM(sol.NetAmount) AS GrossMarginPct,
       SUM(sol.CostAmount) / SUM(sol.Quantity) AS AvgUnitCost
FROM dbo.SalesOrderLines AS sol
JOIN dbo.SalesOrders AS so ON so.SalesOrderId = sol.SalesOrderId
JOIN dbo.Products AS p ON p.ProductId = sol.ProductId
WHERE p.Sku = 'AR-BAT-500'
  AND so.OrderDate >= DATEADD(month, -6, CAST(GETDATE() AS date))
GROUP BY LEFT(CONVERT(varchar(10), so.OrderDate, 23), 7)
ORDER BY YearMonth;
```

**Top 5 products by revenue last quarter**
```sql
SELECT TOP 5 p.ProductName, SUM(sol.NetAmount) AS Revenue
FROM dbo.SalesOrderLines AS sol
JOIN dbo.SalesOrders AS so ON so.SalesOrderId = sol.SalesOrderId
JOIN dbo.Products AS p ON p.ProductId = sol.ProductId
WHERE so.OrderDate >= DATEADD(month, -3, DATEFROMPARTS(YEAR(GETDATE()), (DATEPART(quarter, GETDATE()) - 1) * 3 + 1, 1))
  AND so.OrderDate <  DATEFROMPARTS(YEAR(GETDATE()), (DATEPART(quarter, GETDATE()) - 1) * 3 + 1, 1)
GROUP BY p.ProductName
ORDER BY Revenue DESC;
```

**Revenue and gross margin by region this year**
```sql
SELECT r.RegionName, SUM(sol.NetAmount) AS Revenue,
       100.0 * SUM(sol.NetAmount - sol.CostAmount) / SUM(sol.NetAmount) AS GrossMarginPct
FROM dbo.SalesOrderLines AS sol
JOIN dbo.SalesOrders AS so ON so.SalesOrderId = sol.SalesOrderId
JOIN dbo.Regions AS r ON r.RegionId = so.RegionId
WHERE YEAR(so.OrderDate) = YEAR(GETDATE())
GROUP BY r.RegionName
ORDER BY Revenue DESC;
```

## Publish

**Publish** with a description the Foundry agent can read, for example:

> Answers questions about Alpenrad's sales, revenue, gross margin, customers, regions, products, supplier
> prices versus contracts, and supplier invoices processed by the AI intake (including live data from the last minutes).
