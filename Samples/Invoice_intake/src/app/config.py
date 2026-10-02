"""Settings, read from environment variables (App Service app settings, or a local .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Local development: `azd env get-values > .env` in the repository root.
    for candidate in (Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
except ImportError:  # python-dotenv is optional in production
    pass


@dataclass(frozen=True)
class Settings:
    foundry_account_endpoint: str
    foundry_project_endpoint: str
    chat_deployment: str
    review_agent_name: str
    sales_agent_name: str
    sql_server: str
    sql_database: str
    sql_authentication: str
    storage_account_url: str
    presenter_key: str
    auto_approve_max_amount: Decimal
    min_field_confidence: float
    max_upload_mb: int
    max_concurrent_extractions: int
    uploads_per_session_per_10min: int
    questions_per_session_per_10min: int
    public_url: str


@lru_cache
def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        foundry_account_endpoint=e("FOUNDRY_ACCOUNT_ENDPOINT", "").rstrip("/"),
        foundry_project_endpoint=e("FOUNDRY_PROJECT_ENDPOINT", ""),
        chat_deployment=e("CHAT_DEPLOYMENT_NAME", "gpt-5.2"),
        review_agent_name=e("REVIEW_AGENT_NAME", "invoice-review-agent"),
        sales_agent_name=e("SALES_AGENT_NAME", "sales-analyst"),
        sql_server=e("SQL_SERVER", ""),
        sql_database=e("SQL_DATABASE", "invoicedemo"),
        # Locally your az/azd login is used; in App Service the managed identity.
        sql_authentication=e("SQL_AUTHENTICATION", "ActiveDirectoryDefault"),
        storage_account_url=e("STORAGE_ACCOUNT_URL", ""),
        presenter_key=e("PRESENTER_KEY", ""),
        auto_approve_max_amount=Decimal(e("AUTO_APPROVE_MAX_AMOUNT", "5000")),
        min_field_confidence=float(e("MIN_FIELD_CONFIDENCE", "0.50")),
        max_upload_mb=int(e("MAX_UPLOAD_MB", "8")),
        max_concurrent_extractions=int(e("MAX_CONCURRENT_EXTRACTIONS", "8")),
        uploads_per_session_per_10min=int(e("UPLOADS_PER_SESSION_PER_10MIN", "8")),
        questions_per_session_per_10min=int(e("QUESTIONS_PER_SESSION_PER_10MIN", "15")),
        public_url=e("WEB_APP_URL", ""),
    )
