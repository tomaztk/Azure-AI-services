"""FastAPI app: the audience's mobile page, the presenter screen and the API behind both."""
from __future__ import annotations

import asyncio
import hmac
import io
import logging
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .agent_definitions import PERSONAS
from .config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
STATIC = Path(__file__).parent / "static"

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:  # traces, requests and dependencies to Application Insights
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(logger_name="app")
    except Exception:  # never block startup on telemetry
        log.warning("Application Insights not configured", exc_info=True)

SUGGESTED_QUESTIONS = [
    "What were our top 5 products by revenue last quarter?",
    "Why did gross margin on the 500Wh battery pack drop?",
    "Which suppliers invoice above contract price?",
    "Show revenue by region this year.",
    "How many invoices did the audience scan, and how many needed a human?",
]

services: dict[str, Any] = {}
background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    from .agents import AgentService
    from .content_understanding import ContentUnderstandingClient
    from .pipeline import InvoicePipeline
    from .storage import DocumentStore

    s = get_settings()
    services["agents"] = AgentService()
    services["store"] = DocumentStore()
    services["cu"] = ContentUnderstandingClient(s.foundry_account_endpoint)
    services["pipeline"] = InvoicePipeline(services["cu"], services["agents"], services["store"])
    try:
        n = await asyncio.to_thread(db.fail_stale_processing)
        if n:
            log.info("marked %d interrupted invoices as failed", n)
    except Exception:
        log.warning("database not reachable at startup", exc_info=True)
    yield
    await services["cu"].aclose()


app = FastAPI(title="Alpenrad invoice desk", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ------------------------------------------------------------------ small helpers
class RateLimiter:
    """Sliding-window limit per phone session and per IP address (in memory, per worker)."""

    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: int = 600) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].split(":")[0].strip() or (request.client.host if request.client else "?")


def require_presenter(key: str | None) -> None:
    expected = get_settings().presenter_key
    if not expected:
        raise HTTPException(403, "PRESENTER_KEY is not configured.")
    if not key or not hmac.compare_digest(key, expected):
        raise HTTPException(401, "Wrong presenter key.")


def is_presenter(key: str | None) -> bool:
    expected = get_settings().presenter_key
    return bool(expected and key and hmac.compare_digest(key, expected))


SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def sniff_content_type(data: bytes, declared: str | None) -> str | None:
    """Trust the file's magic bytes, not the browser."""
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return "image/heic"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    return None


# ------------------------------------------------------------------ pages
@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/presenter", include_in_schema=False)
async def presenter() -> FileResponse:
    return FileResponse(STATIC / "presenter.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
async def config() -> dict[str, Any]:
    s = get_settings()
    return {"max_upload_mb": s.max_upload_mb, "personas": PERSONAS, "suggested_questions": SUGGESTED_QUESTIONS,
            "auto_approve_max_amount": float(s.auto_approve_max_amount)}


@app.get("/api/qr.png", include_in_schema=False)
async def qr(request: Request) -> Response:
    import qrcode

    s = get_settings()
    host = os.environ.get("WEBSITE_HOSTNAME")
    url = s.public_url or (f"https://{host}/" if host else str(request.base_url))
    img = qrcode.make(url, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"X-Url": url})


# ------------------------------------------------------------------ invoices
@app.post("/api/invoices")
async def upload_invoice(request: Request, file: UploadFile = File(...), session_id: str = Form(...),
                         source: str = Form("audience"),
                         x_presenter_key: str | None = Header(default=None)) -> dict[str, Any]:
    s = get_settings()
    if not SESSION_RE.match(session_id):
        raise HTTPException(400, "Invalid session.")
    if source not in ("audience", "stage", "cli"):
        raise HTTPException(400, "Invalid source.")
    if source != "audience" and not is_presenter(x_presenter_key):
        raise HTTPException(401, "Only the presenter can upload stage invoices.")
    if source == "audience" and not (limiter.allow(f"up:{session_id}", s.uploads_per_session_per_10min)
                                     and limiter.allow(f"upip:{client_ip(request)}", s.uploads_per_session_per_10min * 4)):
        raise HTTPException(429, "That's a lot of invoices! Please wait a few minutes.")

    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {s.max_upload_mb} MB).")
    content_type = sniff_content_type(data, file.content_type)
    if not content_type:
        raise HTTPException(415, "Please upload a photo (JPEG/PNG/HEIC) or a PDF.")

    invoice_id = await asyncio.to_thread(db.create_invoice, source, session_id, content_type)
    task = asyncio.create_task(services["pipeline"].process(invoice_id, data, content_type, source, session_id))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return {"invoice_id": invoice_id}


@app.get("/api/invoices/{invoice_id}")
async def get_invoice(invoice_id: int, session_id: str | None = None,
                      x_presenter_key: str | None = Header(default=None)) -> JSONResponse:
    inv = await asyncio.to_thread(db.get_invoice, invoice_id)
    presenter = is_presenter(x_presenter_key)
    if not inv or (not presenter and inv.get("SessionId") != session_id):
        raise HTTPException(404, "Invoice not found.")
    inv.pop("BlobPath", None)
    if not presenter:
        inv.pop("SessionId", None)
    return JSONResponse(db.to_json_safe(inv))


@app.get("/api/invoices/{invoice_id}/document")
async def get_document(invoice_id: int, key: str | None = None,
                       x_presenter_key: str | None = Header(default=None)) -> Response:
    require_presenter(x_presenter_key or key)
    inv = await asyncio.to_thread(db.get_invoice, invoice_id)
    if not inv or not inv.get("BlobPath"):
        raise HTTPException(404, "No document.")
    data = await asyncio.to_thread(services["store"].read, inv["BlobPath"])
    return Response(data, media_type=inv.get("ContentType") or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=300"})


class DecisionBody(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


@app.post("/api/invoices/{invoice_id}/approve")
async def approve(invoice_id: int, body: DecisionBody, x_presenter_key: str | None = Header(default=None)):
    require_presenter(x_presenter_key)
    if not await asyncio.to_thread(db.decide_manually, invoice_id, True, "presenter", body.comment):
        raise HTTPException(409, "Invoice can't be approved in its current state.")
    return {"status": "Approved"}


@app.post("/api/invoices/{invoice_id}/reject")
async def reject(invoice_id: int, body: DecisionBody, x_presenter_key: str | None = Header(default=None)):
    require_presenter(x_presenter_key)
    if not await asyncio.to_thread(db.decide_manually, invoice_id, False, "presenter", body.comment):
        raise HTTPException(409, "Invoice can't be rejected in its current state.")
    return {"status": "Rejected"}


@app.get("/api/feed")
async def feed(x_presenter_key: str | None = Header(default=None)) -> JSONResponse:
    require_presenter(x_presenter_key)
    return JSONResponse(db.to_json_safe(await asyncio.to_thread(db.feed)))


# ------------------------------------------------------------------ ask the data
class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=400)
    persona: str = "cfo"
    session_id: str
    conversation_id: str | None = Field(default=None, max_length=100)


@app.post("/api/ask")
async def ask(body: AskBody, request: Request) -> dict[str, Any]:
    s = get_settings()
    if not SESSION_RE.match(body.session_id):
        raise HTTPException(400, "Invalid session.")
    if body.persona not in PERSONAS:
        raise HTTPException(400, "Unknown role.")
    if body.conversation_id and not re.match(r"^[A-Za-z0-9_-]+$", body.conversation_id):
        raise HTTPException(400, "Invalid conversation.")
    if not (limiter.allow(f"ask:{body.session_id}", s.questions_per_session_per_10min)
            and limiter.allow(f"askip:{client_ip(request)}", s.questions_per_session_per_10min * 4)):
        raise HTTPException(429, "Too many questions. Please wait a few minutes.")
    try:
        result = await asyncio.to_thread(services["agents"].ask, body.question, body.persona, body.conversation_id)
    except Exception as ex:
        log.exception("ask failed")
        if "content_filter" in str(ex) or "jailbreak" in str(ex).lower():
            raise HTTPException(400, "The question was blocked by the content safety guardrail.")
        raise HTTPException(502, "The data assistant is busy. Please try again.")
    try:
        await asyncio.to_thread(db.log_question, body.session_id, body.persona, body.question,
                                result["answer"], result["tools"], result["duration_ms"])
    except Exception:
        log.warning("could not log question", exc_info=True)
    return result
