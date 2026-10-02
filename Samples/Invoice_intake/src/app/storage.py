"""Blob storage for uploaded documents and raw extraction results (Entra ID auth, no keys)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from .config import get_settings

EXTENSIONS = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/heic": "heic",
              "image/heif": "heif", "image/tiff": "tiff", "image/bmp": "bmp", "image/webp": "webp"}


class DocumentStore:
    def __init__(self) -> None:
        self.client = BlobServiceClient(get_settings().storage_account_url, credential=DefaultAzureCredential())

    def save_upload(self, invoice_id: int, source: str, data: bytes, content_type: str) -> str:
        ext = EXTENSIONS.get(content_type, "bin")
        name = f"{source}/{datetime.now(timezone.utc):%Y-%m-%d}/{invoice_id}.{ext}"
        self.client.get_blob_client("invoices", name).upload_blob(
            data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
        return f"invoices/{name}"

    def save_extraction(self, invoice_id: int, source: str, result: dict[str, Any]) -> None:
        self.client.get_blob_client("extractions", f"{source}/{invoice_id}.json").upload_blob(
            json.dumps(result), overwrite=True, content_settings=ContentSettings(content_type="application/json"))

    def read(self, blob_path: str) -> bytes:
        container, _, name = blob_path.partition("/")
        return self.client.get_blob_client(container, name).download_blob().readall()
