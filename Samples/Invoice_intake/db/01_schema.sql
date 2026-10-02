/* ============================================================================
   Kolesarstvo s.p. (fictional e-bike parts wholesaler) - demo database
   ----------------------------------------------------------------------------
   Procurement side : Vendors, Contracts, PurchaseOrders, GoodsReceipts,
                      Invoices (written by the AI intake), InvoiceLines, ApprovalLog
   Sales side       : Regions, Customers, Products, SalesOrders, SalesOrderLines
   Demo plumbing    : Calendar, AudienceQuestions, sec.PersonaAccess

   Written to be Fabric-mirroring friendly:
     - every table has a primary key
     - no computed columns, json, xml, (n)text or datetime2(7) columns
   The script is idempotent (only creates what is missing).
   ============================================================================ */

IF SCHEMA_ID(N'sec') IS NULL EXEC (N'CREATE SCHEMA sec');
GO

/* ---------- Reference data ---------- */
IF OBJECT_ID(N'dbo.Regions') IS NULL
CREATE TABLE dbo.Regions (
    RegionId     int           NOT NULL CONSTRAINT PK_Regions PRIMARY KEY,
    RegionCode   nvarchar(10)  NOT NULL,
    RegionName   nvarchar(50)  NOT NULL
);
GO

IF OBJECT_ID(N'dbo.Customers') IS NULL
CREATE TABLE dbo.Customers (
    CustomerId    int           NOT NULL CONSTRAINT PK_Customers PRIMARY KEY,
    CustomerName  nvarchar(100) NOT NULL,
    City          nvarchar(60)  NOT NULL,
    Country       nvarchar(60)  NOT NULL,
    RegionId      int           NOT NULL CONSTRAINT FK_Customers_Regions REFERENCES dbo.Regions(RegionId),
    Segment       nvarchar(30)  NOT NULL   -- 'Dealer' | 'Key account' | 'Online'
);
GO

IF OBJECT_ID(N'dbo.Vendors') IS NULL
CREATE TABLE dbo.Vendors (
    VendorId         int           NOT NULL CONSTRAINT PK_Vendors PRIMARY KEY,
    VendorCode       nvarchar(10)  NOT NULL CONSTRAINT UQ_Vendors_Code UNIQUE,
    VendorName       nvarchar(100) NOT NULL,
    Street           nvarchar(100) NOT NULL,
    City             nvarchar(60)  NOT NULL,
    Country          nvarchar(60)  NOT NULL,
    CountryCode      char(2)       NOT NULL,
    VatId            nvarchar(30)  NOT NULL,
    Iban             nvarchar(40)  NOT NULL,
    PaymentTermDays  int           NOT NULL
);
GO

IF OBJECT_ID(N'dbo.Products') IS NULL
CREATE TABLE dbo.Products (
    ProductId          int            NOT NULL CONSTRAINT PK_Products PRIMARY KEY,
    Sku                nvarchar(20)   NOT NULL CONSTRAINT UQ_Products_Sku UNIQUE,
    ProductName        nvarchar(100)  NOT NULL,
    Category           nvarchar(40)   NOT NULL,
    ListPrice          decimal(12,2)  NOT NULL,   -- selling price to dealers, EUR
    PreferredVendorId  int            NOT NULL CONSTRAINT FK_Products_Vendors REFERENCES dbo.Vendors(VendorId)
);
GO

IF OBJECT_ID(N'dbo.Contracts') IS NULL
CREATE TABLE dbo.Contracts (
    ContractId            int            NOT NULL CONSTRAINT PK_Contracts PRIMARY KEY,
    ContractNumber        nvarchar(20)   NOT NULL,
    VendorId              int            NOT NULL CONSTRAINT FK_Contracts_Vendors REFERENCES dbo.Vendors(VendorId),
    ProductId             int            NOT NULL CONSTRAINT FK_Contracts_Products REFERENCES dbo.Products(ProductId),
    UnitPrice             decimal(12,2)  NOT NULL,   -- agreed purchase price, EUR
    Currency              char(3)        NOT NULL,
    ValidFrom             date           NOT NULL,
    ValidTo               date           NOT NULL,
    MaxPriceDeviationPct  decimal(5,2)   NOT NULL    -- tolerance before an invoice must be reviewed
);
GO

IF OBJECT_ID(N'dbo.Calendar') IS NULL
CREATE TABLE dbo.Calendar (
    DateKey      int           NOT NULL CONSTRAINT PK_Calendar PRIMARY KEY,  -- yyyymmdd
    [Date]       date          NOT NULL,
    [Year]       int           NOT NULL,
    [Quarter]    int           NOT NULL,
    QuarterName  nvarchar(8)   NOT NULL,   -- 2026-Q3
    [Month]      int           NOT NULL,
    MonthName    nvarchar(12)  NOT NULL,
    YearMonth    nvarchar(7)   NOT NULL    -- 2026-09
);
GO

/* ---------- Procurement ---------- */
IF OBJECT_ID(N'dbo.PurchaseOrders') IS NULL
CREATE TABLE dbo.PurchaseOrders (
    PurchaseOrderId  int            NOT NULL CONSTRAINT PK_PurchaseOrders PRIMARY KEY,
    PONumber         nvarchar(30)   NOT NULL CONSTRAINT UQ_PurchaseOrders_Number UNIQUE,
    VendorId         int            NOT NULL CONSTRAINT FK_PurchaseOrders_Vendors REFERENCES dbo.Vendors(VendorId),
    OrderDate        date           NOT NULL,
    Status           nvarchar(20)   NOT NULL,   -- 'Open' | 'Received' | 'Invoiced'
    Currency         char(3)        NOT NULL,
    TotalAmount      decimal(14,2)  NOT NULL
);
GO

IF OBJECT_ID(N'dbo.PurchaseOrderLines') IS NULL
CREATE TABLE dbo.PurchaseOrderLines (
    PurchaseOrderId  int            NOT NULL CONSTRAINT FK_POLines_PurchaseOrders REFERENCES dbo.PurchaseOrders(PurchaseOrderId),
    LineNumber       int            NOT NULL,
    ProductId        int            NOT NULL CONSTRAINT FK_POLines_Products REFERENCES dbo.Products(ProductId),
    Quantity         decimal(12,2)  NOT NULL,
    UnitPrice        decimal(12,2)  NOT NULL,
    CONSTRAINT PK_PurchaseOrderLines PRIMARY KEY (PurchaseOrderId, LineNumber)
);
GO

IF OBJECT_ID(N'dbo.GoodsReceipts') IS NULL
CREATE TABLE dbo.GoodsReceipts (
    GoodsReceiptId    int            NOT NULL CONSTRAINT PK_GoodsReceipts PRIMARY KEY,
    PurchaseOrderId   int            NOT NULL CONSTRAINT FK_GoodsReceipts_PurchaseOrders REFERENCES dbo.PurchaseOrders(PurchaseOrderId),
    ProductId         int            NOT NULL CONSTRAINT FK_GoodsReceipts_Products REFERENCES dbo.Products(ProductId),
    ReceivedQuantity  decimal(12,2)  NOT NULL,
    ReceivedDate      date           NOT NULL
);
GO

IF OBJECT_ID(N'dbo.Invoices') IS NULL
CREATE TABLE dbo.Invoices (
    InvoiceId              int IDENTITY(1,1) NOT NULL CONSTRAINT PK_Invoices PRIMARY KEY,
    InvoiceNumber          nvarchar(60)   NULL,
    VendorId               int            NULL CONSTRAINT FK_Invoices_Vendors REFERENCES dbo.Vendors(VendorId),
    VendorNameRaw          nvarchar(200)  NULL,     -- as read from the document
    PONumber               nvarchar(40)   NULL,
    PurchaseOrderId        int            NULL,
    InvoiceDate            date           NULL,
    DueDate                date           NULL,
    Currency               char(3)        NULL,
    SubtotalAmount         decimal(14,2)  NULL,
    TaxAmount              decimal(14,2)  NULL,
    TotalAmount            decimal(14,2)  NULL,
    Status                 nvarchar(20)   NOT NULL, -- Processing | AutoApproved | NeedsReview | Approved | Rejected | NotAnInvoice | Failed
    ProcessingStage        nvarchar(20)   NULL,     -- uploaded | reading | checking | reviewing | done
    DecisionType           nvarchar(20)   NULL,     -- Auto | Manual | Legacy
    DecisionReason         nvarchar(1000) NULL,
    MinFieldConfidence     decimal(5,3)   NULL,
    MaxPriceDeviationPct   decimal(7,2)   NULL,
    AgentRecommendation    nvarchar(20)   NULL,
    AgentSummary           nvarchar(1000) NULL,
    InjectionDetected      bit            NOT NULL CONSTRAINT DF_Invoices_Injection DEFAULT (0),
    Source                 nvarchar(20)   NOT NULL, -- legacy | stage | audience | cli
    SessionId              nvarchar(64)   NULL,
    BlobPath               nvarchar(400)  NULL,
    ContentType            nvarchar(100)  NULL,
    ReceivedAt             datetime2(3)   NOT NULL CONSTRAINT DF_Invoices_ReceivedAt DEFAULT (SYSUTCDATETIME()),
    DecidedAt              datetime2(3)   NULL,
    DecidedBy              nvarchar(100)  NULL,
    ProcessingMs           int            NULL
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Invoices_Status' AND object_id = OBJECT_ID(N'dbo.Invoices'))
    CREATE INDEX IX_Invoices_Status ON dbo.Invoices (Status, ReceivedAt);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_Invoices_Vendor_Number' AND object_id = OBJECT_ID(N'dbo.Invoices'))
    CREATE INDEX IX_Invoices_Vendor_Number ON dbo.Invoices (VendorId, InvoiceNumber);
GO

IF OBJECT_ID(N'dbo.InvoiceLines') IS NULL
CREATE TABLE dbo.InvoiceLines (
    InvoiceId          int            NOT NULL CONSTRAINT FK_InvoiceLines_Invoices REFERENCES dbo.Invoices(InvoiceId),
    LineNumber         int            NOT NULL,
    ProductId          int            NULL,
    Sku                nvarchar(40)   NULL,
    Description        nvarchar(300)  NULL,
    Quantity           decimal(12,2)  NULL,
    UnitPrice          decimal(12,2)  NULL,
    LineAmount         decimal(14,2)  NULL,
    ContractUnitPrice  decimal(12,2)  NULL,
    PriceDeviationPct  decimal(7,2)   NULL,
    CONSTRAINT PK_InvoiceLines PRIMARY KEY (InvoiceId, LineNumber)
);
GO

IF OBJECT_ID(N'dbo.ApprovalLog') IS NULL
CREATE TABLE dbo.ApprovalLog (
    ApprovalLogId  int IDENTITY(1,1) NOT NULL CONSTRAINT PK_ApprovalLog PRIMARY KEY,
    InvoiceId      int            NOT NULL CONSTRAINT FK_ApprovalLog_Invoices REFERENCES dbo.Invoices(InvoiceId),
    Action         nvarchar(30)   NOT NULL,   -- AutoApproved | RoutedToReview | Approved | Rejected | NotAnInvoice | Failed
    Actor          nvarchar(100)  NOT NULL,
    Comment        nvarchar(1000) NULL,
    CreatedAt      datetime2(3)   NOT NULL CONSTRAINT DF_ApprovalLog_CreatedAt DEFAULT (SYSUTCDATETIME())
);
GO

/* ---------- Sales ---------- */
IF OBJECT_ID(N'dbo.SalesOrders') IS NULL
CREATE TABLE dbo.SalesOrders (
    SalesOrderId  int           NOT NULL CONSTRAINT PK_SalesOrders PRIMARY KEY,
    OrderNumber   nvarchar(20)  NOT NULL,
    OrderDate     date          NOT NULL,
    CustomerId    int           NOT NULL CONSTRAINT FK_SalesOrders_Customers REFERENCES dbo.Customers(CustomerId),
    RegionId      int           NOT NULL CONSTRAINT FK_SalesOrders_Regions REFERENCES dbo.Regions(RegionId),
    Channel       nvarchar(20)  NOT NULL   -- 'Dealer portal' | 'Field sales' | 'Phone'
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_SalesOrders_Date' AND object_id = OBJECT_ID(N'dbo.SalesOrders'))
    CREATE INDEX IX_SalesOrders_Date ON dbo.SalesOrders (OrderDate) INCLUDE (CustomerId, RegionId);
GO

IF OBJECT_ID(N'dbo.SalesOrderLines') IS NULL
CREATE TABLE dbo.SalesOrderLines (
    SalesOrderId  int            NOT NULL CONSTRAINT FK_SalesOrderLines_SalesOrders REFERENCES dbo.SalesOrders(SalesOrderId),
    LineNumber    int            NOT NULL,
    ProductId     int            NOT NULL CONSTRAINT FK_SalesOrderLines_Products REFERENCES dbo.Products(ProductId),
    Quantity      int            NOT NULL,
    UnitPrice     decimal(12,2)  NOT NULL,
    DiscountPct   decimal(5,2)   NOT NULL,
    NetAmount     decimal(14,2)  NOT NULL,   -- Quantity * UnitPrice * (1 - DiscountPct/100), stored (no computed columns)
    UnitCost      decimal(12,2)  NOT NULL,   -- purchase cost at time of sale (average approved invoice price that month)
    CostAmount    decimal(14,2)  NOT NULL,   -- Quantity * UnitCost
    CONSTRAINT PK_SalesOrderLines PRIMARY KEY (SalesOrderId, LineNumber)
);
GO

/* ---------- Demo plumbing ---------- */
IF OBJECT_ID(N'dbo.AudienceQuestions') IS NULL
CREATE TABLE dbo.AudienceQuestions (
    QuestionId  int IDENTITY(1,1) NOT NULL CONSTRAINT PK_AudienceQuestions PRIMARY KEY,
    SessionId   nvarchar(64)   NULL,
    Persona     nvarchar(40)   NOT NULL,
    Question    nvarchar(500)  NOT NULL,
    Answer      nvarchar(4000) NULL,
    ToolsUsed   nvarchar(400)  NULL,
    DurationMs  int            NULL,
    AskedAt     datetime2(3)   NOT NULL CONSTRAINT DF_AudienceQuestions_AskedAt DEFAULT (SYSUTCDATETIME())
);
GO

-- Personas for the "Ask the data" tab. Row-level security (03_security.sql) reads this table.
IF OBJECT_ID(N'sec.PersonaAccess') IS NULL
CREATE TABLE sec.PersonaAccess (
    Persona            nvarchar(40)  NOT NULL CONSTRAINT PK_PersonaAccess PRIMARY KEY,
    DisplayName        nvarchar(60)  NOT NULL,
    CanSeeSales        bit           NOT NULL,
    CanSeeProcurement  bit           NOT NULL,
    RegionId           int           NULL      -- NULL = all regions
);
GO
