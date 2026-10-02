/* Row-level security for the "Ask the data" personas.

   The web app sets SESSION_CONTEXT('persona') before it runs a question's SQL:
     cfo          -> all sales, all procurement
     dach_sales   -> sales rows of region DACH only, no procurement data
     procurement  -> procurement data only, no sales
   When no persona is set (the invoice pipeline, the setup scripts, Fabric mirroring)
   every row is visible. Azure SQL enforces this, not the prompt. */

MERGE sec.PersonaAccess AS t
USING (VALUES
    (N'cfo',         N'CFO (all data)',          1, 1, NULL),
    (N'dach_sales',  N'Sales manager DACH',      1, 0, 1),
    (N'procurement', N'Procurement clerk',       0, 1, NULL)
) AS s (Persona, DisplayName, CanSeeSales, CanSeeProcurement, RegionId)
ON t.Persona = s.Persona
WHEN MATCHED THEN UPDATE SET DisplayName = s.DisplayName, CanSeeSales = s.CanSeeSales,
                             CanSeeProcurement = s.CanSeeProcurement, RegionId = s.RegionId
WHEN NOT MATCHED THEN INSERT (Persona, DisplayName, CanSeeSales, CanSeeProcurement, RegionId)
                      VALUES (s.Persona, s.DisplayName, s.CanSeeSales, s.CanSeeProcurement, s.RegionId);
GO

-- Drop the policy first so the predicate functions can be (re)created.
IF EXISTS (SELECT 1 FROM sys.security_policies WHERE name = N'DemoPersonaPolicy')
    DROP SECURITY POLICY sec.DemoPersonaPolicy;
GO

CREATE OR ALTER FUNCTION sec.fn_SalesAccess (@RegionId int)
RETURNS TABLE
WITH SCHEMABINDING
AS RETURN
    SELECT 1 AS AccessResult
    WHERE SESSION_CONTEXT(N'persona') IS NULL
       OR EXISTS (SELECT 1
                  FROM sec.PersonaAccess pa
                  WHERE pa.Persona = CAST(SESSION_CONTEXT(N'persona') AS nvarchar(40))
                    AND pa.CanSeeSales = 1
                    AND (pa.RegionId IS NULL OR pa.RegionId = @RegionId));
GO

CREATE OR ALTER FUNCTION sec.fn_SalesLineAccess (@SalesOrderId int)
RETURNS TABLE
WITH SCHEMABINDING
AS RETURN
    SELECT 1 AS AccessResult
    WHERE SESSION_CONTEXT(N'persona') IS NULL
       OR EXISTS (SELECT 1
                  FROM dbo.SalesOrders so
                  JOIN sec.PersonaAccess pa
                    ON pa.Persona = CAST(SESSION_CONTEXT(N'persona') AS nvarchar(40))
                  WHERE so.SalesOrderId = @SalesOrderId
                    AND pa.CanSeeSales = 1
                    AND (pa.RegionId IS NULL OR pa.RegionId = so.RegionId));
GO

CREATE OR ALTER FUNCTION sec.fn_ProcurementAccess (@Key int)
RETURNS TABLE
WITH SCHEMABINDING
AS RETURN
    SELECT 1 AS AccessResult
    WHERE @Key IS NOT NULL
      AND (SESSION_CONTEXT(N'persona') IS NULL
           OR EXISTS (SELECT 1
                      FROM sec.PersonaAccess pa
                      WHERE pa.Persona = CAST(SESSION_CONTEXT(N'persona') AS nvarchar(40))
                        AND pa.CanSeeProcurement = 1));
GO

CREATE SECURITY POLICY sec.DemoPersonaPolicy
    ADD FILTER PREDICATE sec.fn_SalesAccess(RegionId)            ON dbo.Customers,
    ADD FILTER PREDICATE sec.fn_SalesAccess(RegionId)            ON dbo.SalesOrders,
    ADD FILTER PREDICATE sec.fn_SalesLineAccess(SalesOrderId)    ON dbo.SalesOrderLines,
    ADD FILTER PREDICATE sec.fn_ProcurementAccess(InvoiceId)     ON dbo.Invoices,
    ADD FILTER PREDICATE sec.fn_ProcurementAccess(InvoiceId)     ON dbo.InvoiceLines,
    ADD FILTER PREDICATE sec.fn_ProcurementAccess(ContractId)    ON dbo.Contracts,
    ADD FILTER PREDICATE sec.fn_ProcurementAccess(PurchaseOrderId) ON dbo.PurchaseOrders
WITH (STATE = ON);
GO
