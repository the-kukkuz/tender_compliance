"""Lightweight SQLite connection and schema management for MVP audit records."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_CREATE_AUDIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    analysis_id TEXT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    summary TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploaded_documents (
    document_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    role TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    sha256_hash TEXT,
    pages_json TEXT NOT NULL,
    total_chars INTEGER NOT NULL,
    is_text_based INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_analyses (
    analysis_id TEXT PRIMARY KEY,
    tender_document_id TEXT NOT NULL,
    bidder_document_ids_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permit_checklists (
    permit_pack_id TEXT PRIMARY KEY,
    analysis_id TEXT UNIQUE NOT NULL,
    contract_reference TEXT,
    planned_start_date TEXT,
    site_location TEXT,
    checklist_items_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    unresolved_conditions_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    full_name TEXT NOT NULL DEFAULT '',
    organisation_name TEXT NOT NULL DEFAULT '',
    organization_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'SEEKER',
    roles_json TEXT NOT NULL DEFAULT '["SEEKER"]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bidder_profiles (
    profile_id TEXT PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    organisation_name TEXT NOT NULL DEFAULT '',
    business_identifiers_json TEXT NOT NULL DEFAULT '[]',
    categories_json TEXT NOT NULL DEFAULT '[]',
    experience_years REAL NOT NULL DEFAULT 0.0,
    experience_summary TEXT NOT NULL DEFAULT '',
    past_projects_json TEXT NOT NULL DEFAULT '[]',
    certifications_json TEXT NOT NULL DEFAULT '[]',
    annual_turnover REAL NOT NULL DEFAULT 0.0,
    currency TEXT NOT NULL DEFAULT 'USD',
    turnover_currency TEXT NOT NULL DEFAULT 'USD',
    financial_audited INTEGER NOT NULL DEFAULT 1,
    locations_json TEXT NOT NULL DEFAULT '[]',
    location TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    safety_manual_approved INTEGER NOT NULL DEFAULT 1,
    other_qualifications_json TEXT NOT NULL DEFAULT '[]',
    supporting_document_ids_json TEXT NOT NULL DEFAULT '[]',
    uploaded_document_ids_json TEXT NOT NULL DEFAULT '[]',
    is_verified INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tenders (
    tender_id TEXT PRIMARY KEY,
    issuer_user_id TEXT NOT NULL,
    issuer_organisation TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PUBLISHED',
    submission_deadline TEXT NOT NULL,
    financial_threshold REAL,
    financial_currency TEXT DEFAULT 'USD',
    geographic_restrictions_json TEXT NOT NULL DEFAULT '[]',
    required_certifications_json TEXT NOT NULL DEFAULT '[]',
    min_experience_years REAL DEFAULT 0.0,
    safety_requirements_json TEXT NOT NULL DEFAULT '[]',
    required_documents_json TEXT NOT NULL DEFAULT '[]',
    document_id TEXT NOT NULL,
    document_filename TEXT DEFAULT '',
    reference_code TEXT DEFAULT '',
    location TEXT DEFAULT '',
    publication_date TEXT DEFAULT '',
    fields_json TEXT DEFAULT '{}',
    requirements_json TEXT DEFAULT '[]',
    is_confirmed INTEGER DEFAULT 1,
    confirmed_at TEXT DEFAULT '',
    issuer_id TEXT DEFAULT '',
    issuer_name TEXT DEFAULT '',
    issuer_org TEXT DEFAULT '',
    extracted_requirements_json TEXT NOT NULL DEFAULT '[]',
    requirement_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tender_requirement_versions (
    version_id TEXT PRIMARY KEY,
    tender_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    requirements_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tender_submissions (
    submission_id TEXT PRIMARY KEY,
    tender_id TEXT NOT NULL,
    requirement_version INTEGER NOT NULL DEFAULT 1,
    bidder_id TEXT NOT NULL DEFAULT '',
    bidder_user_id TEXT NOT NULL DEFAULT '',
    bidder_name TEXT NOT NULL DEFAULT '',
    bidder_org TEXT NOT NULL DEFAULT '',
    bidder_organisation TEXT NOT NULL DEFAULT '',
    bidder_document_ids_json TEXT NOT NULL DEFAULT '[]',
    bidder_profile_json TEXT NOT NULL DEFAULT '{}',
    profile_snapshot_json TEXT NOT NULL DEFAULT '{}',
    compliance_score REAL NOT NULL DEFAULT 0.0,
    match_status TEXT NOT NULL DEFAULT '',
    analysis_id TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'SUBMITTED',
    review_status TEXT NOT NULL DEFAULT 'SUBMITTED',
    award_justification TEXT NOT NULL DEFAULT '',
    assessment_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL DEFAULT '{}',
    submitted_at TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""

_REQUIRED_COLUMNS = {
    "users": [
        ("name", "TEXT NOT NULL DEFAULT ''"),
        ("full_name", "TEXT NOT NULL DEFAULT ''"),
        ("organisation_name", "TEXT NOT NULL DEFAULT ''"),
        ("organization_name", "TEXT NOT NULL DEFAULT ''"),
        ("role", "TEXT NOT NULL DEFAULT 'SEEKER'"),
        ("roles_json", "TEXT NOT NULL DEFAULT '[\"SEEKER\"]'"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ],
    "bidder_profiles": [
        ("profile_id", "TEXT NOT NULL DEFAULT ''"),
        ("organisation_name", "TEXT NOT NULL DEFAULT ''"),
        ("business_identifiers_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("categories_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("experience_years", "REAL NOT NULL DEFAULT 0.0"),
        ("experience_summary", "TEXT NOT NULL DEFAULT ''"),
        ("past_projects_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("certifications_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("annual_turnover", "REAL NOT NULL DEFAULT 0.0"),
        ("currency", "TEXT NOT NULL DEFAULT 'USD'"),
        ("turnover_currency", "TEXT NOT NULL DEFAULT 'USD'"),
        ("financial_audited", "INTEGER NOT NULL DEFAULT 1"),
        ("locations_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("location", "TEXT NOT NULL DEFAULT ''"),
        ("industry", "TEXT NOT NULL DEFAULT ''"),
        ("safety_manual_approved", "INTEGER NOT NULL DEFAULT 1"),
        ("other_qualifications_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("supporting_document_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("uploaded_document_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("is_verified", "INTEGER NOT NULL DEFAULT 1"),
        ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ],
    "tenders": [
        ("issuer_id", "TEXT NOT NULL DEFAULT ''"),
        ("issuer_user_id", "TEXT NOT NULL DEFAULT ''"),
        ("issuer_name", "TEXT NOT NULL DEFAULT ''"),
        ("issuer_org", "TEXT NOT NULL DEFAULT ''"),
        ("issuer_organisation", "TEXT NOT NULL DEFAULT ''"),
        ("reference_code", "TEXT NOT NULL DEFAULT ''"),
        ("location", "TEXT NOT NULL DEFAULT ''"),
        ("publication_date", "TEXT NOT NULL DEFAULT ''"),
        ("financial_threshold", "REAL DEFAULT 0.0"),
        ("financial_currency", "TEXT DEFAULT 'USD'"),
        ("document_id", "TEXT NOT NULL DEFAULT ''"),
        ("document_filename", "TEXT NOT NULL DEFAULT ''"),
        ("fields_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("requirements_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("is_confirmed", "INTEGER NOT NULL DEFAULT 1"),
        ("confirmed_at", "TEXT NOT NULL DEFAULT ''"),
        ("geographic_restrictions_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("required_certifications_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("min_experience_years", "REAL DEFAULT 0.0"),
        ("safety_requirements_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("required_documents_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("extracted_requirements_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("requirement_version", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "tender_submissions": [
        ("requirement_version", "INTEGER NOT NULL DEFAULT 1"),
        ("bidder_id", "TEXT NOT NULL DEFAULT ''"),
        ("bidder_user_id", "TEXT NOT NULL DEFAULT ''"),
        ("bidder_name", "TEXT NOT NULL DEFAULT ''"),
        ("bidder_org", "TEXT NOT NULL DEFAULT ''"),
        ("bidder_organisation", "TEXT NOT NULL DEFAULT ''"),
        ("bidder_document_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("bidder_profile_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("profile_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("compliance_score", "REAL NOT NULL DEFAULT 0.0"),
        ("match_status", "TEXT NOT NULL DEFAULT ''"),
        ("analysis_id", "TEXT NOT NULL DEFAULT ''"),
        ("result_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("status", "TEXT NOT NULL DEFAULT 'SUBMITTED'"),
        ("review_status", "TEXT NOT NULL DEFAULT 'SUBMITTED'"),
        ("award_justification", "TEXT NOT NULL DEFAULT ''"),
        ("assessment_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("summary_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("submitted_at", "TEXT NOT NULL DEFAULT ''"),
        ("reviewed_at", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ],
}

_CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_audit_events_analysis_id ON audit_events (analysis_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_permit_checklists_analysis_id ON permit_checklists (analysis_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_bidder_profiles_user_id ON bidder_profiles (user_id);
CREATE INDEX IF NOT EXISTS idx_tenders_issuer ON tenders (issuer_user_id);
CREATE INDEX IF NOT EXISTS idx_tenders_status_category ON tenders (status, category);
CREATE INDEX IF NOT EXISTS idx_tenders_deadline ON tenders (submission_deadline);
CREATE INDEX IF NOT EXISTS idx_tender_versions_tender_id ON tender_requirement_versions (tender_id, version_number);
CREATE INDEX IF NOT EXISTS idx_tender_submissions_tender_id ON tender_submissions (tender_id);
CREATE INDEX IF NOT EXISTS idx_tender_submissions_bidder_id ON tender_submissions (bidder_user_id);
"""


def get_db_path(custom_path: Optional[str] = None) -> Path:
    """Resolve the configured SQLite database file path and ensure parent dir exists."""
    raw_path = custom_path or get_settings().sqlite_db_path
    db_path = Path(raw_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_sqlite_db(custom_path: Optional[str] = None) -> bool:
    """Initialize SQLite schema and safely migrate existing tables without data loss."""
    try:
        db_path = get_db_path(custom_path)
        with sqlite3.connect(str(db_path), timeout=5.0) as conn:
            # 1. Base table creation
            conn.executescript(_CREATE_AUDIT_TABLE_SQL)

            # 2. Schema migration / column synchronization
            for table_name, req_cols in _REQUIRED_COLUMNS.items():
                cur = conn.execute(f"PRAGMA table_info({table_name})")
                existing_cols = {row[1] for row in cur.fetchall()}
                for col_name, col_def in req_cols:
                    if col_name not in existing_cols:
                        try:
                            conn.execute(
                                f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def}"
                            )
                        except sqlite3.OperationalError:
                            pass

            # 3. Create indexes safely
            conn.executescript(_CREATE_INDEXES_SQL)
            conn.commit()
        return True
    except sqlite3.Error as exc:
        logger.warning(f"SQLite initialization warning: {exc}")
        return False
    except OSError as exc:
        logger.warning(f"SQLite directory creation warning: {exc}")
        return False


def check_database_health(custom_path: Optional[str] = None) -> bool:
    """Verify SQLite connectivity without blocking document analysis."""
    try:
        db_path = get_db_path(custom_path)
        with sqlite3.connect(str(db_path), timeout=2.0) as conn:
            conn.execute("SELECT 1")
        return True
    except (sqlite3.Error, OSError):
        return False


@contextmanager
def sqlite_connection(custom_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a SQLite connection with Row factory."""
    db_path = get_db_path(custom_path)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
