"""Creates the schema, views and row-level security, grants the web app access, and seeds data.

    python scripts/setup_database.py            # create what's missing, seed if empty
    python scripts/setup_database.py --reseed   # wipe all rows and seed again (e.g. the day before your session)

Reseeding works while Fabric mirroring is running (it only deletes and inserts rows).
"""
from __future__ import annotations

import argparse
import os
from datetime import date

import common as c
import seed_data


def grant_web_app() -> None:
    """Database user for the web app's managed identity (runs outside a transaction)."""
    name = os.environ.get("WEB_APP_NAME")
    if not name:
        c.warn("WEB_APP_NAME not set; skipping database user for the web app.")
        return
    object_id = os.environ.get("WEB_APP_PRINCIPAL_ID", "")
    with c.sql_connect(autocommit=True) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sys.database_principals WHERE name = ?", (name,))
        if cur.fetchone()[0] == 0:
            try:
                cur.execute(f"CREATE USER [{name}] FROM EXTERNAL PROVIDER;")
            except Exception as ex:  # display-name lookup can fail in some tenants; use the object ID instead
                if not object_id:
                    raise
                c.warn(f"Name lookup failed ({ex}); retrying with WITH OBJECT_ID.")
                cur = conn.cursor()
                cur.execute(f"CREATE USER [{name}] FROM EXTERNAL PROVIDER WITH OBJECT_ID = '{object_id}';")
        for role in ("db_datareader", "db_datawriter"):
            cur.execute(f"ALTER ROLE {role} ADD MEMBER [{name}];")
    c.ok(f"Web app identity '{name}' can read and write data")


def is_empty(conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dbo.Products")
    return cur.fetchone()[0] == 0


def seed(conn, as_of: date | None = None) -> None:
    data = seed_data.generate(as_of)
    cur = conn.cursor()
    cur.execute("EXEC sp_set_session_context @key = N'persona', @value = NULL;")
    for table in data.tables:
        c.bulk_insert(conn, table.name, table.columns, table.rows, table.identity_insert)
        c.ok(f"{table.name:<24} {len(table.rows):>7,} rows")
    print(seed_data.summary(data))


def wipe(conn) -> None:
    cur = conn.cursor()
    cur.execute("EXEC sp_set_session_context @key = N'persona', @value = NULL;")
    for table in seed_data.DELETE_ORDER:
        cur.execute(f"DELETE FROM {table};")
    conn.commit()
    c.ok("All rows deleted")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reseed", action="store_true", help="delete all rows and seed again")
    parser.add_argument("--as-of", type=date.fromisoformat, help="seed date (default: today)")
    args = parser.parse_args()

    c.load_env()
    c.step("Database schema, views and row-level security")
    with c.sql_connect() as conn:
        for f in ("01_schema.sql", "02_views.sql", "03_security.sql"):
            c.run_sql_file(conn, c.DB_DIR / f)
            c.ok(f)
    grant_web_app()

    with c.sql_connect() as conn:
        c.step("Demo data")
        if args.reseed:
            wipe(conn)
        if is_empty(conn):
            seed(conn, args.as_of)
        else:
            c.ok("Data already present (use --reseed to regenerate)")


if __name__ == "__main__":
    main()
