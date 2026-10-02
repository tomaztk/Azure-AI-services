"""azd preprovision hook: stores values the Bicep template needs in the azd environment.

- AZURE_PRINCIPAL_NAME: your UPN, used as the label of the SQL Entra admin and as Fabric capacity admin
- PRESENTER_KEY: random key that protects the presenter screen
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess


def azd_set(name: str, value: str) -> None:
    subprocess.run(["azd", "env", "set", name, value], check=False, capture_output=True, text=True)
    print(f"  set {name}")


def main() -> None:
    if not shutil.which("azd"):
        return
    if not os.environ.get("AZURE_PRINCIPAL_NAME"):
        upn = ""
        az = shutil.which("az") or shutil.which("az.cmd")
        if az:
            r = subprocess.run([az, "ad", "signed-in-user", "show", "--query", "userPrincipalName", "-o", "tsv"],
                               capture_output=True, text=True)
            upn = r.stdout.strip()
        if upn:
            azd_set("AZURE_PRINCIPAL_NAME", upn)
        else:
            print("  Could not read your UPN with 'az ad signed-in-user show'. "
                  "Run 'az login', or set it: azd env set AZURE_PRINCIPAL_NAME you@contoso.com")
    if not os.environ.get("PRESENTER_KEY"):
        azd_set("PRESENTER_KEY", secrets.token_urlsafe(18))


if __name__ == "__main__":
    main()
