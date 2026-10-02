/* Analytical views used by the web app's "Ask the data" tools.
   Views are NOT mirrored to Fabric; fabric/sql_endpoint_views.sql recreates them
   on the mirrored database's SQL analytics endpoint. */

CREATE OR ALTER VIEW dbo.vw_SalesLines AS
SELECT
    so.SalesOrderId,
    so.OrderNumber,
    so.OrderDate,
    cal.[Year],
    cal.QuarterName,
    cal.YearMonth,
    so.RegionId,
    r.RegionCode,
    r.RegionName,
    so.CustomerId,
    cu.CustomerName,
    cu.Country,
    cu.Segment,
    so.Channel,
    sol.LineNumber,
    sol.ProductId,
    p.Sku,
    p.ProductName,
    p.Category,
    v.VendorName                                         AS SupplierName,
    sol.Quantity,
    sol.UnitPrice,
    sol.DiscountPct,
    sol.NetAmount                                        AS Revenue,
    sol.UnitCost,
    sol.CostAmount,
    CAST(sol.NetAmount - sol.CostAmount AS decimal(14,2)) AS GrossMargin
FROM dbo.SalesOrders       so
JOIN dbo.SalesOrderLines   sol ON sol.SalesOrderId = so.SalesOrderId
JOIN dbo.Customers         cu  ON cu.CustomerId    = so.CustomerId
JOIN dbo.Regions           r   ON r.RegionId       = so.RegionId
JOIN dbo.Products          p   ON p.ProductId      = sol.ProductId
JOIN dbo.Vendors           v   ON v.VendorId       = p.PreferredVendorId
JOIN dbo.Calendar          cal ON cal.[Date]       = so.OrderDate;
GO

CREATE OR ALTER VIEW dbo.vw_InvoiceLineDeviations AS
SELECT
    i.InvoiceId,
    i.InvoiceNumber,
    i.InvoiceDate,
    CONVERT(char(7), i.InvoiceDate, 126)                 AS YearMonth,
    i.Status,
    i.DecisionType,
    i.Source,
    i.ReceivedAt,
    i.VendorId,
    COALESCE(v.VendorName, i.VendorNameRaw)              AS VendorName,
    il.LineNumber,
    il.ProductId,
    COALESCE(p.Sku, il.Sku)                              AS Sku,
    COALESCE(p.ProductName, il.Description)              AS ProductName,
    il.Quantity,
    il.UnitPrice,
    il.ContractUnitPrice,
    il.PriceDeviationPct,
    CAST(il.Quantity * (il.UnitPrice - il.ContractUnitPrice) AS decimal(14,2)) AS OverpaymentAmount,
    il.LineAmount
FROM dbo.Invoices       i
JOIN dbo.InvoiceLines   il ON il.InvoiceId = i.InvoiceId
LEFT JOIN dbo.Vendors   v  ON v.VendorId   = i.VendorId
LEFT JOIN dbo.Products  p  ON p.ProductId  = il.ProductId;
GO

CREATE OR ALTER VIEW dbo.vw_InvoiceOverview AS
SELECT
    i.InvoiceId,
    i.InvoiceNumber,
    i.InvoiceDate,
    i.ReceivedAt,
    i.DecidedAt,
    i.Status,
    i.DecisionType,
    i.DecisionReason,
    i.Source,
    i.VendorId,
    COALESCE(v.VendorName, i.VendorNameRaw) AS VendorName,
    i.PONumber,
    i.TotalAmount,
    i.Currency,
    i.MaxPriceDeviationPct,
    i.MinFieldConfidence,
    i.InjectionDetected,
    i.ProcessingMs,
    i.DecidedBy
FROM dbo.Invoices      i
LEFT JOIN dbo.Vendors  v ON v.VendorId = i.VendorId;
GO
