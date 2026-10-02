"""Helpers shared by the setup scripts: azd environment, SQL access, logging."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

# azd pipes hook output; on Windows that would default to cp1252 and fail on ✓/✗.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
SAMPLES_DIR = ROOT / "samples"


# ---------------------------------------------------------------- output
def step(title: str) -> None:
    print(f"\n\033[1;36m==> {title}\033[0m", flush=True)


def ok(msg: str) -> None:
    print(f"    \033[32m✓\033[0m {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"    \033[33m!\033[0m {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"    \033[31m✗\033[0m {msg}", flush=True)


# ---------------------------------------------------------------- azd environment
def load_env() -> None:
    """Make azd environment values available as environment variables.

    azd hooks already export them. When a script runs on its own, read them with
    `azd env get-values` (falls back to a .env file in the repository root)."""
    if os.environ.get("SQL_SERVER") and os.environ.get("FOUNDRY_PROJECT_ENDPOINT"):
        return
    text = ""
    if shutil.which("azd"):
        try:
            text = subprocess.run(["azd", "env", "get-values"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout
        except subprocess.CalledProcessError:
            text = ""
    if not text and (ROOT / ".env").exists():
        text = (ROOT / ".env").read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"?(.*?)"?\s*$', line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2)


def env(name: str, default: str | None = None, required: bool = True) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        fail(f"Missing setting {name}. Run 'azd provision' first or add it to .env.")
        sys.exit(1)
    return value or ""


def azd_set(name: str, value: str) -> None:
    if shutil.which("azd"):
        subprocess.run(["azd", "env", "set", name, value], cwd=ROOT, check=False,
                       capture_output=True, text=True)
    os.environ[name] = value


def az(*args: str, check: bool = True) -> str:
    """Run an Azure CLI command and return stdout."""
    exe = shutil.which("az") or shutil.which("az.cmd")
    if not exe:
        raise RuntimeError("Azure CLI (az) not found on PATH.")
    sub = os.environ.get("AZURE_SUBSCRIPTION_ID")
    if sub and "--subscription" not in args:
        args = (*args, "--subscription", sub)  # same subscription as azd, whatever `az account show` says
    result = subprocess.run([exe, *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


# ---------------------------------------------------------------- SQL
def sql_connect(autocommit: bool = False):
    """Connect to Azure SQL with your Microsoft Entra identity (az login / azd auth)."""
    import mssql_python

    server = env("SQL_SERVER")
    database = env("SQL_DATABASE")
    auth = os.environ.get("SQL_AUTHENTICATION_LOCAL", "ActiveDirectoryDefault")
    conn_str = (f"Server=tcp:{server},1433;Database={database};Authentication={auth};"
                "Encrypt=yes;TrustServerCertificate=no;")
    return mssql_python.connect(conn_str, autocommit=autocommit, timeout=60)


def split_batches(sql_text: str) -> list[str]:
    """Split a script on lines that contain only GO (like sqlcmd does)."""
    batches, current = [], []
    for line in sql_text.splitlines():
        if re.fullmatch(r"\s*GO\s*;?\s*", line, flags=re.IGNORECASE):
            if "".join(current).strip():
                batches.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if "".join(current).strip():
        batches.append("\n".join(current))
    return batches


def run_sql_file(conn, path: Path, replacements: dict[str, str] | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    for key, value in (replacements or {}).items():
        text = text.replace("{{" + key + "}}", value)
    cur = conn.cursor()
    for batch in split_batches(text):
        cur.execute(batch)
    conn.commit()


def sql_literal(v) -> str:
    """Render a Python value as a T-SQL literal (only used for generated seed data)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return "'" + v.isoformat(sep=" ", timespec="milliseconds") + "'"
    if isinstance(v, date):
        return "'" + v.isoformat() + "'"
    return "N'" + str(v).replace("'", "''") + "'"


def bulk_insert(conn, table: str, columns: list[str], rows: list[tuple], identity_insert: bool = False,
                batch_size: int = 900) -> None:
    """Fast multi-row INSERT ... VALUES for seed data (SQL Server allows 1,000 rows per statement)."""
    if not rows:
        return
    cur = conn.cursor()
    cols = ", ".join(f"[{c}]" for c in columns)
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        values = ",\n".join("(" + ", ".join(sql_literal(v) for v in r) + ")" for r in chunk)
        stmt = f"INSERT INTO {table} ({cols}) VALUES\n{values};"
        if identity_insert:
            stmt = f"SET IDENTITY_INSERT {table} ON;\n{stmt}\nSET IDENTITY_INSERT {table} OFF;"
        cur.execute(stmt)
    conn.commit()
