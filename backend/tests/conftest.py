"""Test fixtures for Bid2Work AI backend tests."""

from __future__ import annotations

import io
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def force_mock_llm_mode_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure automated tests run in deterministic mock mode without network calls by default."""
    monkeypatch.setenv("LLM_ENABLED", "false")
    get_settings.cache_clear()


def build_text_pdf_bytes(page_texts: List[str]) -> bytes:
    """Create a valid in-memory PDF with extractable page-level text using pypdf."""
    writer = PdfWriter()

    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)

        font_dict = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_ref = writer._add_object(font_dict)

        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_ref}
                )
            }
        )
        page[NameObject("/Resources")] = resources

        escaped = (
            text.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
        content_stream = DecodedStreamObject()
        content_stream.set_data(
            f"BT /F1 11 Tf 50 720 Td ({escaped}) Tj ET".encode("latin-1", errors="replace")
        )
        stream_ref = writer._add_object(content_stream)
        page[NameObject("/Contents")] = stream_ref

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def build_empty_pdf_bytes(page_count: int = 1) -> bytes:
    """Create a PDF with blank pages containing 0 text (simulating scanned / empty pages)."""
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def build_encrypted_pdf_bytes(password: str = "secret") -> bytes:
    """Create an encrypted password-protected PDF."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Provide a FastAPI TestClient wired to an isolated temporary SQLite DB and upload dir."""
    test_db = tmp_path / "test_audit.db"
    test_uploads = tmp_path / "uploads"
    monkeypatch.setenv("DATABASE_URL", str(test_db))
    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))
    monkeypatch.setenv("TEMP_UPLOAD_DIR", str(test_uploads))
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
