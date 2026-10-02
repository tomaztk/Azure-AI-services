"""Send invoices to the running app from the command line (intake without a phone).

Use it to rehearse, to calibrate the confidence threshold, as a stand-in for an email/SharePoint
intake, or as a small load test before the event.

    python scripts/send_invoice.py samples/01_clean_brennerwerk.pdf
    python scripts/send_invoice.py samples/*.pdf --source stage          # shows up as a stage invoice
    python scripts/send_invoice.py samples/01_clean_brennerwerk.jpg --repeat 60 --concurrency 20 --source audience
    python scripts/send_invoice.py samples/*.pdf --url http://localhost:8000

Stage/CLI uploads need the presenter key (read from the azd environment).
"""
from __future__ import annotations

import argparse
import asyncio
import mimetypes
import os
import secrets
import time
from pathlib import Path

import httpx

import common as c

FINAL = {"AutoApproved", "NeedsReview", "Approved", "Rejected", "NotAnInvoice", "Failed"}


async def send_one(client: httpx.AsyncClient, url: str, path: Path, source: str, key: str) -> dict:
    session = secrets.token_hex(8)
    headers = {"X-Presenter-Key": key} if key else {}
    started = time.monotonic()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    r = await client.post(f"{url}/api/invoices", headers=headers,
                          files={"file": (path.name, path.read_bytes(), ctype)},
                          data={"session_id": session, "source": source})
    if r.status_code != 200:
        return {"file": path.name, "Status": f"HTTP {r.status_code}", "DecisionReason": r.text[:200]}
    invoice_id = r.json()["invoice_id"]
    while time.monotonic() - started < 240:
        await asyncio.sleep(1.5)
        inv = (await client.get(f"{url}/api/invoices/{invoice_id}", params={"session_id": session},
                                headers=headers)).json()
        if inv.get("Status") in FINAL:
            inv["file"] = path.name
            inv["seconds"] = round(time.monotonic() - started, 1)
            return inv
    return {"file": path.name, "Status": "timeout"}


async def main_async(args: argparse.Namespace) -> None:
    c.load_env()
    url = (args.url or c.env("WEB_APP_URL")).rstrip("/")
    key = os.environ.get("PRESENTER_KEY", "") if args.source != "audience" else ""
    files = [Path(f) for f in args.files] * args.repeat
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=120) as client:
        async def guarded(p: Path):
            async with sem:
                return await send_one(client, url, p, args.source, key)
        started = time.monotonic()
        results = await asyncio.gather(*(guarded(p) for p in files))
    print(f"\n{'file':<42} {'status':<13} {'sec':>5} {'conf':>5}  reason")
    for r in results:
        conf = r.get("MinFieldConfidence")
        print(f"{r['file']:<42} {r.get('Status', ''):<13} {r.get('seconds', ''):>5} "
              f"{conf if conf is not None else '':>5}  {(r.get('DecisionReason') or '')[:110]}")
    print(f"\n{len(results)} invoices in {time.monotonic() - started:.1f} s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+")
    parser.add_argument("--url", help="app URL (default: WEB_APP_URL from azd)")
    parser.add_argument("--source", choices=["cli", "stage", "audience"], default="cli")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=5)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
