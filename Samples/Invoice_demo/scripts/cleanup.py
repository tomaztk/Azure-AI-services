"""Reset the live demo data (keeps the seeded history).

    python scripts/cleanup.py --live        # before the session: remove all stage/audience/CLI invoices and questions
    python scripts/cleanup.py --audience    # after the session: remove what the audience uploaded (DB rows + blobs)

Blobs under invoices/audience/ are also deleted automatically after 2 days by a lifecycle rule.
"""
from __future__ import annotations

import argparse

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

import common as c


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="remove all non-legacy invoices and all questions")
    group.add_argument("--audience", action="store_true", help="remove audience invoices, questions and uploads")
    parser.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args()
    c.load_env()

    where = "Source <> N'legacy'" if args.live else "Source = N'audience'"
    if not args.yes and input(f"Delete invoices WHERE {where} and all audience questions? [y/N] ").lower() != "y":
        return
    c.step("Database")
    with c.sql_connect() as conn:
        cur = conn.cursor()
        for sql in (f"DELETE FROM dbo.ApprovalLog WHERE InvoiceId IN (SELECT InvoiceId FROM dbo.Invoices WHERE {where})",
                    f"DELETE FROM dbo.InvoiceLines WHERE InvoiceId IN (SELECT InvoiceId FROM dbo.Invoices WHERE {where})",
                    f"DELETE FROM dbo.Invoices WHERE {where}",
                    "DELETE FROM dbo.AudienceQuestions"):
            cur.execute(sql)
            c.ok(f"{cur.rowcount:>6} rows  {sql[:70]}")

    c.step("Blob storage")
    service = BlobServiceClient(c.env("STORAGE_ACCOUNT_URL"), credential=DefaultAzureCredential())
    prefixes = ["stage/", "audience/", "cli/"] if args.live else ["audience/"]
    for container in ("invoices", "extractions"):
        cc = service.get_container_client(container)
        n = 0
        for prefix in prefixes:
            for blob in cc.list_blobs(name_starts_with=prefix):
                cc.delete_blob(blob.name)
                n += 1
        c.ok(f"{n:>6} blobs deleted from {container}")


if __name__ == "__main__":
    main()
