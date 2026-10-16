"""azd postprovision hook: everything after the Azure resources exist.

  1. presenter key -> web app setting
  2. your IP -> SQL firewall (so the scripts can connect from your machine)
  3. schema, views, web app DB user, seed data
  4. Content Understanding model defaults
  5. the Foundry data agent
  6. printable sample invoices + QR code

Safe to run again: python scripts/postprovision.py
"""
from __future__ import annotations

import os
import socket
import sys
import time
from typing import Callable

import httpx

import common as c


def retry(fn: Callable[[], None], what: str, attempts: int = 6, wait_s: int = 30) -> bool:
    """New role assignments can take a few minutes to apply; retry instead of failing."""
    for i in range(1, attempts + 1):
        try:
            fn()
            return True
        except (Exception, SystemExit) as ex:  # noqa: BLE001
            if i == attempts:
                c.fail(f"{what} failed: {ex}")
                return False
            c.warn(f"{what} not ready yet ({str(ex)[:160]}). Retrying in {wait_s}s ({i}/{attempts})...")
            time.sleep(wait_s)
    return False


def presenter_key() -> None:
    c.step("Presenter key")
    key = os.environ.get("PRESENTER_KEY")
    if not key:
        import secrets
        key = secrets.token_urlsafe(18)
        c.azd_set("PRESENTER_KEY", key)
    try:
        c.az("webapp", "config", "appsettings", "set", "-g", c.env("AZURE_RESOURCE_GROUP"), "-n", c.env("WEB_APP_NAME"),
             "--settings", f"PRESENTER_KEY={key}", f"WEB_APP_URL={c.env('WEB_APP_URL')}", "-o", "none")
        c.ok("stored in the web app settings")
    except Exception as ex:  # noqa: BLE001
        c.warn(f"Could not update app settings ({ex}). The key is still in your azd environment.")


def sql_firewall() -> None:
    c.step("SQL firewall rule for this machine")
    try:
        ip = httpx.get("https://api.ipify.org", timeout=15).text.strip()
        name = "client-" + "".join(ch for ch in socket.gethostname() if ch.isalnum())[:40]
        c.az("sql", "server", "firewall-rule", "create", "-g", c.env("AZURE_RESOURCE_GROUP"),
             "-s", c.env("SQL_SERVER_NAME"), "-n", name, "--start-ip-address", ip, "--end-ip-address", ip, "-o", "none")
        c.ok(f"{ip} allowed ({name})")
    except Exception as ex:  # noqa: BLE001
        c.warn(f"Could not add a firewall rule automatically ({ex}). Add your IP in the Azure portal: "
               "SQL server > Networking > Add your client IPv4 address.")


def database() -> None:
    import setup_database as sdb

    c.step("Database schema and views")
    with c.sql_connect() as conn:
        for f in ("01_schema.sql", "02_views.sql"):
            c.run_sql_file(conn, c.DB_DIR / f)
            c.ok(f)
    sdb.grant_web_app()
    with c.sql_connect() as conn:
        c.step("Demo data")
        if sdb.is_empty(conn):
            sdb.seed(conn)
        else:
            c.ok("Data already present (python scripts/setup_database.py --reseed to regenerate)")


def main() -> None:
    c.load_env()
    presenter_key()
    sql_firewall()
    time.sleep(5)  # firewall rules take a moment
    db_ok = retry(database, "Database setup", attempts=4, wait_s=20)

    import configure_content_understanding
    import create_agents
    import generate_sample_invoices

    cu_ok = retry(configure_content_understanding.main, "Content Understanding setup")
    agents_ok = retry(create_agents.main, "Agent creation")
    sys.argv = [sys.argv[0]]
    generate_sample_invoices.main()

    url = c.env("WEB_APP_URL")
    key = os.environ.get("PRESENTER_KEY", "")
    c.step("Done")
    print(f"""
    Audience page   : {url}
    Presenter screen: {url}/presenter?key={key}
    Sample invoices : {c.SAMPLES_DIR}

    Next steps
      1. azd deploy                     (if you ran 'azd provision' only; 'azd up' already deployed)
      2. Print samples/all_invoices_handout.pdf and scan one with your phone
      3. Open the presenter screen on your laptop and ask the data agent a question on your phone
    """)
    if not (db_ok and cu_ok and agents_ok):
        c.warn("Some steps failed; fix the message above and run: python scripts/postprovision.py")


if __name__ == "__main__":
    main()
