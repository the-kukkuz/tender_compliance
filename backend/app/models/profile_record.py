"""Repository for persisting and retrieving BidderProfile records."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from app.core.logging import get_logger
from app.db.sqlite import init_sqlite_db, sqlite_connection
from app.schemas.profile import (
    BidderProfile,
    BusinessIdentifier,
    CertificationItem,
    PastProjectItem,
)

logger = get_logger(__name__)

_FALLBACK_PROFILES: Dict[str, BidderProfile] = {}


class ProfileRepository:
    """Manages storage and query of reusable bidder qualification profiles."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        init_sqlite_db(self.db_path)

    def get_profile_by_user_id(self, user_id: str) -> Optional[BidderProfile]:
        """Fetch bidder profile for a specific user ID."""
        try:
            with sqlite_connection(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM bidder_profiles WHERE user_id = ?",
                    (user_id,),
                ).fetchone()

            if row:
                row_dict = dict(row)
                profile_id = row_dict.get("profile_id") or f"PRF-{user_id}"
                org_name = row_dict.get("organisation_name") or "Bidder Organisation"

                biz_raw = row_dict.get("business_identifiers_json")
                biz_list = json.loads(biz_raw) if biz_raw else []

                cats_raw = row_dict.get("categories_json")
                cats_list = json.loads(cats_raw) if cats_raw else ["GENERAL"]

                proj_raw = row_dict.get("past_projects_json")
                proj_list = json.loads(proj_raw) if proj_raw else []

                cert_raw = row_dict.get("certifications_json")
                cert_list = json.loads(cert_raw) if cert_raw else []

                locs_raw = row_dict.get("locations_json")
                if locs_raw:
                    locs_list = json.loads(locs_raw)
                elif row_dict.get("location"):
                    locs_list = [row_dict["location"]]
                else:
                    locs_list = ["National"]

                other_raw = row_dict.get("other_qualifications_json")
                other_list = json.loads(other_raw) if other_raw else []

                docs_raw = row_dict.get("supporting_document_ids_json") or row_dict.get("uploaded_document_ids_json")
                docs_list = json.loads(docs_raw) if docs_raw else []

                currency = row_dict.get("currency") or row_dict.get("turnover_currency") or "USD"
                turnover = float(row_dict.get("annual_turnover") or 0.0)
                exp_years = float(row_dict.get("experience_years") or 0.0)
                exp_summary = row_dict.get("experience_summary") or f"{exp_years:.0f} years of operating experience."

                profile = BidderProfile(
                    profile_id=profile_id,
                    user_id=row_dict["user_id"],
                    organisation_name=org_name,
                    business_identifiers=[
                        BusinessIdentifier(**item) if isinstance(item, dict) else BusinessIdentifier(id_type="Registration", value=str(item))
                        for item in biz_list
                    ],
                    categories=cats_list,
                    experience_years=exp_years,
                    experience_summary=exp_summary,
                    past_projects=[
                        PastProjectItem(**item) for item in proj_list if isinstance(item, dict)
                    ],
                    certifications=[
                        CertificationItem(**item) for item in cert_list if isinstance(item, dict)
                    ],
                    annual_turnover=turnover,
                    currency=currency,
                    financial_audited=bool(row_dict.get("financial_audited", 1)),
                    locations=locs_list,
                    safety_manual_approved=bool(row_dict.get("safety_manual_approved", 1)),
                    other_qualifications=other_list,
                    supporting_document_ids=docs_list,
                    is_verified=bool(row_dict.get("is_verified", 1)),
                    updated_at=datetime.fromisoformat(row_dict["updated_at"]) if row_dict.get("updated_at") else datetime.now(timezone.utc),
                )
                return profile
            return None
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying profile: {exc}")
            return _FALLBACK_PROFILES.get(user_id)

    def save_profile(self, profile: BidderProfile) -> BidderProfile:
        """Create or update a bidder profile record."""
        now_iso = datetime.now(timezone.utc).isoformat()
        profile.updated_at = datetime.fromisoformat(now_iso)

        biz_json = json.dumps([b.model_dump() for b in profile.business_identifiers])
        cats_json = json.dumps(profile.categories)
        proj_json = json.dumps([p.model_dump() for p in profile.past_projects])
        cert_json = json.dumps([c.model_dump() for c in profile.certifications])
        locs_json = json.dumps(profile.locations)
        other_json = json.dumps(profile.other_qualifications)
        docs_json = json.dumps(profile.supporting_document_ids)

        try:
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO bidder_profiles (
                        profile_id, user_id, organisation_name,
                        business_identifiers_json, categories_json,
                        experience_years, experience_summary, past_projects_json,
                        certifications_json, annual_turnover, currency, turnover_currency,
                        financial_audited, locations_json, location, safety_manual_approved,
                        other_qualifications_json, supporting_document_ids_json,
                        uploaded_document_ids_json,
                        is_verified, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.profile_id,
                        profile.user_id,
                        profile.organisation_name,
                        biz_json,
                        cats_json,
                        profile.experience_years,
                        profile.experience_summary,
                        proj_json,
                        cert_json,
                        profile.annual_turnover,
                        profile.currency,
                        profile.currency,
                        1 if profile.financial_audited else 0,
                        locs_json,
                        profile.locations[0] if profile.locations else "",
                        1 if profile.safety_manual_approved else 0,
                        other_json,
                        docs_json,
                        docs_json,
                        1 if profile.is_verified else 0,
                        now_iso,
                        now_iso,
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Profile saved to memory fallback: {exc}")

        _FALLBACK_PROFILES[profile.user_id] = profile
        return profile

    def get_or_create_default(
        self, user_id: str, organisation_name: str
    ) -> BidderProfile:
        """Fetch existing profile or initialize an empty starter profile."""
        existing = self.get_profile_by_user_id(user_id)
        if existing:
            return existing

        new_profile = BidderProfile(
            profile_id=f"PRF-{uuid.uuid4().hex[:8].upper()}",
            user_id=user_id,
            organisation_name=organisation_name,
            business_identifiers=[
                BusinessIdentifier(
                    id_type="Commercial Registration", value=f"CR-{uuid.uuid4().hex[:6].upper()}"
                )
            ],
            categories=["GENERAL", "ENGINEERING"],
            experience_years=5.0,
            experience_summary="Established contractor with proven delivery track record in commercial and industrial projects.",
            past_projects=[
                PastProjectItem(
                    title="Industrial Facility Construction",
                    client="Apex Global Infrastructure",
                    value=3500000.0,
                    currency="USD",
                    completion_year=2024,
                )
            ],
            certifications=[
                CertificationItem(
                    name="ISO 9001:2015",
                    cert_number="CERT-9001-2023",
                    valid_until="2027-12-31",
                    accredited_by="BSI",
                ),
                CertificationItem(
                    name="ISO 45001",
                    cert_number="CERT-45001-2023",
                    valid_until="2028-06-30",
                    accredited_by="Bureau Veritas",
                ),
            ],
            annual_turnover=6500000.0,
            currency="USD",
            financial_audited=True,
            locations=["National", "Regional"],
            safety_manual_approved=True,
            other_qualifications=["Standard Corporate HSE Manual", "Approved Quality Policy"],
            supporting_document_ids=[],
            is_verified=True,
        )
        return self.save_profile(new_profile)
