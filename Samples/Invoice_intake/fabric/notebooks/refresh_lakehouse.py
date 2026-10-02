# Fabric notebook (PySpark): copy the mirrored Azure SQL tables into the lakehouse as analysis-ready tables.
#
# Why this step exists: the Fabric IQ ontology binds to *managed* lakehouse tables (not shortcuts,
# not mirrored tables), and the ontology graph can't read Decimal columns. This notebook
#   - reads the mirrored tables from OneLake,
#   - flattens sales orders and invoice lines into simple fact tables with single-column keys,
#   - casts decimals to double,
#   - overwrites the lakehouse tables.
#
# How to use: create a notebook in your Fabric workspace, attach the lakehouse "AlpenradLH" as the
# default lakehouse, paste this file into one cell, set the two parameters, run it. Schedule it
# (e.g. every 15 minutes) so the semantic model and ontology stay fresh.

WORKSPACE = "alpenrad-demo"          # Fabric workspace name (or its GUID)
MIRRORED_DB = "invoicedemo"          # name of the mirrored database item (or its GUID)

from pyspark.sql import DataFrame, functions as F
from pyspark.sql.types import DecimalType

item = MIRRORED_DB if len(MIRRORED_DB) == 36 and MIRRORED_DB.count("-") == 4 else f"{MIRRORED_DB}.MirroredDatabase"
BASE = f"abfss://{WORKSPACE}@onelake.dfs.fabric.microsoft.com/{item}/Tables"


def read(table: str) -> DataFrame:
    """Mirrored tables live under Tables/dbo/<table> (older mirrors: Tables/dbo_<table>)."""
    for path in (f"{BASE}/dbo/{table}", f"{BASE}/dbo_{table}", f"{BASE}/{table}"):
        try:
            return spark.read.format("delta").load(path)
        except Exception:
            continue
    raise FileNotFoundError(f"Mirrored table {table} not found under {BASE}")


def doubles(df: DataFrame) -> DataFrame:
    """Fabric Graph (used by the ontology) doesn't support Decimal; use double."""
    for f in df.schema.fields:
        if isinstance(f.dataType, DecimalType):
            df = df.withColumn(f.name, F.col(f.name).cast("double"))
    return df


def save(df: DataFrame, name: str) -> None:
    doubles(df).write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(name)
    print(f"{name:<14} {spark.table(name).count():>8} rows")


date_key = lambda c: F.date_format(F.col(c), "yyyyMMdd").cast("int")

vendors = read("Vendors").select("VendorId", "VendorCode", "VendorName", "City", "Country", "PaymentTermDays")
save(read("Regions"), "Regions")
save(read("Customers").select("CustomerId", "CustomerName", "City", "Country", "Segment", "RegionId"), "Customers")
save(vendors, "Vendors")
save(read("Products").join(
        vendors.select(F.col("VendorId").alias("PreferredVendorId"), F.col("VendorName").alias("SupplierName")),
        "PreferredVendorId", "left")
     .select("ProductId", "Sku", "ProductName", "Category", "ListPrice", "PreferredVendorId", "SupplierName"), "Products")
# Avoid names like Date/Year/Month that are reserved words in the graph query language.
save(read("Calendar").select("DateKey", F.col("Date").alias("CalendarDate"), F.col("Year").alias("CalendarYear"),
                             F.col("Quarter").alias("QuarterNumber"), "QuarterName",
                             F.col("Month").alias("MonthNumber"), "MonthName", "YearMonth"), "Calendar")
save(read("Contracts").select("ContractId", "ContractNumber", "VendorId", "ProductId",
                             F.col("UnitPrice").alias("ContractUnitPrice"), "Currency", "ValidFrom", "ValidTo",
                             "MaxPriceDeviationPct"), "Contracts")

orders = read("SalesOrders")
save(read("SalesOrderLines").join(orders, "SalesOrderId").select(
        (F.col("SalesOrderId") * 10 + F.col("LineNumber")).cast("int").alias("SalesLineId"),
        "SalesOrderId", "OrderNumber", "OrderDate", date_key("OrderDate").alias("OrderDateKey"),
        "CustomerId", "RegionId", "Channel", "ProductId",
        F.col("Quantity").cast("double").alias("QuantitySold"),
        F.col("UnitPrice").alias("SalesUnitPrice"), "DiscountPct",
        F.col("NetAmount").alias("Revenue"), "UnitCost", "CostAmount",
        (F.col("NetAmount") - F.col("CostAmount")).alias("GrossMargin")), "SalesLines")

invoices = read("Invoices").where(F.col("Status") != "Processing")
save(invoices.select(
        "InvoiceId", "InvoiceNumber", "VendorId", "VendorNameRaw", "PONumber", "InvoiceDate",
        date_key("InvoiceDate").alias("InvoiceDateKey"), "DueDate", "Currency", "SubtotalAmount", "TaxAmount",
        "TotalAmount", "Status", F.col("Status").isin("AutoApproved", "Approved").alias("IsApproved"),
        "DecisionType", "DecisionReason", "MaxPriceDeviationPct", "MinFieldConfidence", "InjectionDetected",
        "Source", "ReceivedAt", "DecidedAt", "DecidedBy", "ProcessingMs"), "Invoices")
save(read("InvoiceLines").join(invoices.select("InvoiceId"), "InvoiceId").select(
        (F.col("InvoiceId") * 100 + F.col("LineNumber")).cast("int").alias("InvoiceLineId"),
        "InvoiceId", "ProductId", "Sku", "Description",
        F.col("Quantity").alias("QuantityInvoiced"), F.col("UnitPrice").alias("InvoiceUnitPrice"),
        "LineAmount", "ContractUnitPrice", "PriceDeviationPct",
        (F.col("Quantity") * (F.col("UnitPrice") - F.col("ContractUnitPrice"))).alias("OverpaymentAmount")),
     "InvoiceLines")
print("Done. Refresh the ontology graph if you want the ontology to show the newest rows.")
