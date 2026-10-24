"""Repository for persisting tenders, requirement versions, and bidder submissions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.db.sqlite import init_sqlite_db, sqlite_connection
from app.schemas.compliance import (
    ComplianceSummaryMetrics,
    RequirementAssessment,
    TenderRequirement,
)
from app.schemas.profile import BidderProfile
from app.schemas.tender import (
    TenderCreateRequest,
    TenderResponse,
    TenderStatus,
    TenderSubmission,
    TenderUpdateRequest,
)

logger = get_logger(__name__)

_FALLBACK_TENDERS: Dict[str, TenderResponse] = {}
_FALLBACK_VERSIONS: Dict[str, List[TenderRequirement]] = {}
_FALLBACK_SUBMISSIONS: Dict[str, TenderSubmission] = {}


class TenderRepository:
    """Manages storage and query of tenders, requirement versions, and submissions."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        init_sqlite_db(self.db_path)

    def _row_to_tender(self, row: sqlite3.Row) -> TenderResponse:
        row_dict = dict(row)
        issuer_user_id = row_dict.get("issuer_user_id") or row_dict.get("issuer_id") or ""
        issuer_org = row_dict.get("issuer_organisation") or row_dict.get("issuer_org") or ""

        geo_raw = row_dict.get("geographic_restrictions_json")
        geo_list = json.loads(geo_raw) if geo_raw else []

        certs_raw = row_dict.get("required_certifications_json")
        certs_list = json.loads(certs_raw) if certs_raw else []

        safety_raw = row_dict.get("safety_requirements_json")
        safety_list = json.loads(safety_raw) if safety_raw else []

        docs_raw = row_dict.get("required_documents_json")
        docs_list = json.loads(docs_raw) if docs_raw else []

        reqs_raw = row_dict.get("extracted_requirements_json") or row_dict.get("requirements_json")
        reqs_list = [TenderRequirement(**item) for item in json.loads(reqs_raw)] if reqs_raw else []

        status_str = row_dict.get("status") or "PUBLISHED"
        try:
            st = TenderStatus(status_str)
        except ValueError:
            st = TenderStatus.PUBLISHED

        return TenderResponse(
            tender_id=row_dict["tender_id"],
            issuer_user_id=issuer_user_id,
            issuer_organisation=issuer_org,
            title=row_dict["title"],
            description=row_dict.get("description") or "",
            category=row_dict.get("category") or "GENERAL",
            status=st,
            submission_deadline=row_dict.get("submission_deadline") or "2026-12-31",
            financial_threshold=(
                float(row_dict["financial_threshold"])
                if row_dict.get("financial_threshold") is not None
                else None
            ),
            financial_currency=row_dict.get("financial_currency") or "USD",
            geographic_restrictions=geo_list,
            required_certifications=certs_list,
            min_experience_years=float(row_dict.get("min_experience_years") or 0.0),
            safety_requirements=safety_list,
            required_documents=docs_list,
            document_id=row_dict.get("document_id") or "",
            extracted_requirements=reqs_list,
            requirement_version=int(row_dict.get("requirement_version") or 1),
            created_at=datetime.fromisoformat(row_dict["created_at"]) if row_dict.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(row_dict["updated_at"]) if row_dict.get("updated_at") else datetime.now(timezone.utc),
        )

    def create_tender(
        self,
        issuer_user_id: str,
        issuer_organisation: str,
        create_req: TenderCreateRequest,
    ) -> TenderResponse:
        """Create and publish a new tender record with requirement version 1."""
        tender_id = f"TND-{uuid.uuid4().hex[:8].upper()}"
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        reqs_json = json.dumps([r.model_dump() for r in create_req.extracted_requirements])
        geo_json = json.dumps(create_req.geographic_restrictions)
        certs_json = json.dumps(create_req.required_certifications)
        safety_json = json.dumps(create_req.safety_requirements)
        docs_json = json.dumps(create_req.required_documents)

        tender_resp = TenderResponse(
            tender_id=tender_id,
            issuer_user_id=issuer_user_id,
            issuer_organisation=issuer_organisation,
            title=create_req.title,
            description=create_req.description,
            category=create_req.category,
            status=TenderStatus.PUBLISHED,
            submission_deadline=create_req.submission_deadline,
            financial_threshold=create_req.financial_threshold,
            financial_currency=create_req.financial_currency,
            geographic_restrictions=create_req.geographic_restrictions,
            required_certifications=create_req.required_certifications,
            min_experience_years=create_req.min_experience_years,
            safety_requirements=create_req.safety_requirements,
            required_documents=create_req.required_documents,
            document_id=create_req.document_id,
            extracted_requirements=create_req.extracted_requirements,
            requirement_version=1,
            created_at=now_dt,
            updated_at=now_dt,
        )

        try:
            loc_str = ", ".join(create_req.geographic_restrictions) if create_req.geographic_restrictions else "National"
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO tenders (
                        tender_id, issuer_id, issuer_user_id, issuer_name, issuer_org, issuer_organisation,
                        title, reference_code, category, description, location, publication_date, status,
                        submission_deadline, min_experience_years, financial_threshold, financial_currency,
                        document_id, document_filename, fields_json, requirements_json,
                        is_confirmed, confirmed_at, geographic_restrictions_json, required_certifications_json,
                        safety_requirements_json, required_documents_json, extracted_requirements_json,
                        requirement_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tender_id,
                        issuer_user_id,
                        issuer_user_id,
                        issuer_organisation,
                        issuer_organisation,
                        issuer_organisation,
                        create_req.title,
                        tender_id,
                        create_req.category,
                        create_req.description,
                        loc_str,
                        now_iso,
                        "PUBLISHED",
                        create_req.submission_deadline,
                        create_req.min_experience_years or 0.0,
                        create_req.financial_threshold or 0.0,
                        create_req.financial_currency or "USD",
                        create_req.document_id,
                        f"{create_req.document_id}.pdf",
                        "{}",
                        reqs_json,
                        1,
                        now_iso,
                        geo_json,
                        certs_json,
                        safety_json,
                        docs_json,
                        reqs_json,
                        1,
                        now_iso,
                        now_iso,
                    ),
                )
                # Archive version 1
                v_id = f"VER-{tender_id}-001"
                conn.execute(
                    """
                    INSERT INTO tender_requirement_versions (
                        version_id, tender_id, version_number, requirements_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (v_id, tender_id, 1, reqs_json, now_iso),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Tender saved to fallback buffer: {exc}")

        _FALLBACK_TENDERS[tender_id] = tender_resp
        _FALLBACK_VERSIONS[f"{tender_id}_1"] = create_req.extracted_requirements
        return tender_resp

    def get_tender(self, tender_id: str) -> Optional[TenderResponse]:
        """Fetch tender by tender_id."""
        try:
            with sqlite_connection(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM tenders WHERE tender_id = ?", (tender_id,)
                ).fetchone()
                if row:
                    t = self._row_to_tender(row)
                    return t
                return None
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying tender: {exc}")
            return _FALLBACK_TENDERS.get(tender_id)

    def update_tender(
        self, tender_id: str, updates: TenderUpdateRequest
    ) -> Optional[TenderResponse]:
        """Update tender fields and increment version if requirements are modified."""
        existing = self.get_tender(tender_id)
        if not existing:
            return None

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        new_title = updates.title or existing.title
        new_desc = updates.description or existing.description
        new_cat = updates.category or existing.category
        new_deadline = updates.submission_deadline or existing.submission_deadline
        new_thresh = (
            updates.financial_threshold
            if updates.financial_threshold is not None
            else existing.financial_threshold
        )
        new_curr = updates.financial_currency or existing.financial_currency
        new_geo = (
            updates.geographic_restrictions
            if updates.geographic_restrictions is not None
            else existing.geographic_restrictions
        )
        new_certs = (
            updates.required_certifications
            if updates.required_certifications is not None
            else existing.required_certifications
        )
        new_exp = (
            updates.min_experience_years
            if updates.min_experience_years is not None
            else existing.min_experience_years
        )
        new_safety = (
            updates.safety_requirements
            if updates.safety_requirements is not None
            else existing.safety_requirements
        )
        new_docs = (
            updates.required_documents
            if updates.required_documents is not None
            else existing.required_documents
        )
        new_status = updates.status or existing.status

        new_reqs = (
            updates.extracted_requirements
            if updates.extracted_requirements is not None
            else existing.extracted_requirements
        )

        new_version = existing.requirement_version
        if updates.extracted_requirements is not None:
            new_version += 1

        reqs_json = json.dumps([r.model_dump() for r in new_reqs])
        geo_json = json.dumps(new_geo)
        certs_json = json.dumps(new_certs)
        safety_json = json.dumps(new_safety)
        docs_json = json.dumps(new_docs)

        updated_resp = TenderResponse(
            tender_id=tender_id,
            issuer_user_id=existing.issuer_user_id,
            issuer_organisation=existing.issuer_organisation,
            title=new_title,
            description=new_desc,
            category=new_cat,
            status=new_status,
            submission_deadline=new_deadline,
            financial_threshold=new_thresh,
            financial_currency=new_curr,
            geographic_restrictions=new_geo,
            required_certifications=new_certs,
            min_experience_years=new_exp,
            safety_requirements=new_safety,
            required_documents=new_docs,
            document_id=existing.document_id,
            extracted_requirements=new_reqs,
            requirement_version=new_version,
            created_at=existing.created_at,
            updated_at=now_dt,
        )

        try:
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE tenders SET
                        title = ?, description = ?, category = ?, status = ?,
                        submission_deadline = ?, financial_threshold = ?, financial_currency = ?,
                        geographic_restrictions_json = ?, required_certifications_json = ?,
                        min_experience_years = ?, safety_requirements_json = ?,
                        required_documents_json = ?, extracted_requirements_json = ?,
                        requirement_version = ?, updated_at = ?
                    WHERE tender_id = ?
                    """,
                    (
                        new_title,
                        new_desc,
                        new_cat,
                        new_status.value,
                        new_deadline,
                        new_thresh,
                        new_curr,
                        geo_json,
                        certs_json,
                        new_exp,
                        safety_json,
                        docs_json,
                        reqs_json,
                        new_version,
                        now_iso,
                        tender_id,
                    ),
                )
                if updates.extracted_requirements is not None:
                    v_id = f"VER-{tender_id}-{new_version:03d}"
                    conn.execute(
                        """
                        INSERT INTO tender_requirement_versions (
                            version_id, tender_id, version_number, requirements_json, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (v_id, tender_id, new_version, reqs_json, now_iso),
                    )
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Tender update error, using fallback: {exc}")

        _FALLBACK_TENDERS[tender_id] = updated_resp
        if updates.extracted_requirements is not None:
            _FALLBACK_VERSIONS[f"{tender_id}_{new_version}"] = new_reqs
        return updated_resp

    def list_published_tenders(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[TenderResponse], int]:
        """Fetch all eligible published tenders with total count."""
        try:
            with sqlite_connection(self.db_path) as conn:
                if category:
                    count_row = conn.execute(
                        "SELECT COUNT(*) as c FROM tenders WHERE status = 'PUBLISHED' AND category = ?",
                        (category,),
                    ).fetchone()
                    total = count_row["c"] if count_row else 0

                    rows = conn.execute(
                        """
                        SELECT * FROM tenders
                        WHERE status = 'PUBLISHED' AND category = ?
                        ORDER BY submission_deadline ASC
                        LIMIT ? OFFSET ?
                        """,
                        (category, limit, offset),
                    ).fetchall()
                else:
                    count_row = conn.execute(
                        "SELECT COUNT(*) as c FROM tenders WHERE status = 'PUBLISHED'"
                    ).fetchone()
                    total = count_row["c"] if count_row else 0

                    rows = conn.execute(
                        """
                        SELECT * FROM tenders
                        WHERE status = 'PUBLISHED'
                        ORDER BY submission_deadline ASC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    ).fetchall()

                return [self._row_to_tender(r) for r in rows], total
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying published tenders: {exc}")

        # Fallback in-memory
        all_t = [
            t
            for t in _FALLBACK_TENDERS.values()
            if t.status == TenderStatus.PUBLISHED
            and (not category or t.category == category)
        ]
        all_t.sort(key=lambda x: x.submission_deadline)
        return all_t[offset : offset + limit], len(all_t)

    def list_tenders_by_issuer(self, issuer_user_id: str) -> List[TenderResponse]:
        """Fetch all tenders created by a specific issuer."""
        try:
            with sqlite_connection(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM tenders
                    WHERE issuer_user_id = ?
                    ORDER BY created_at DESC
                    """,
                    (issuer_user_id,),
                ).fetchall()
                return [self._row_to_tender(r) for r in rows]
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying issuer tenders: {exc}")

        return [
            t for t in _FALLBACK_TENDERS.values() if t.issuer_user_id == issuer_user_id
        ]

    def get_requirement_version(
        self, tender_id: str, version_number: int
    ) -> Optional[List[TenderRequirement]]:
        """Retrieve historical requirements list for a specific version."""
        key = f"{tender_id}_{version_number}"
        if key in _FALLBACK_VERSIONS:
            return _FALLBACK_VERSIONS[key]

        try:
            with sqlite_connection(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT requirements_json
                    FROM tender_requirement_versions
                    WHERE tender_id = ? AND version_number = ?
                    """,
                    (tender_id, version_number),
                ).fetchone()
                if row:
                    reqs = [
                        TenderRequirement(**item)
                        for item in json.loads(row["requirements_json"])
                    ]
                    _FALLBACK_VERSIONS[key] = reqs
                    return reqs
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying requirement version: {exc}")

        return None

    def create_submission(
        self,
        tender_id: str,
        requirement_version: int,
        bidder_user_id: str,
        bidder_organisation: str,
        profile: BidderProfile,
        compliance_score: float,
        assessment: List[RequirementAssessment],
        summary: ComplianceSummaryMetrics,
        bidder_document_ids: Optional[List[str]] = None,
    ) -> TenderSubmission:
        """Create and store a bidder submission against a specific tender ID and version."""
        sub_id = f"SUB-{uuid.uuid4().hex[:8].upper()}"
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        prof_json = profile.model_dump_json()
        doc_ids = bidder_document_ids or profile.supporting_document_ids
        docs_json = json.dumps(doc_ids)
        ass_json = json.dumps([a.model_dump(mode="json") for a in assessment])
        sum_json = summary.model_dump_json()

        sub_obj = TenderSubmission(
            submission_id=sub_id,
            tender_id=tender_id,
            requirement_version=requirement_version,
            bidder_user_id=bidder_user_id,
            bidder_organisation=bidder_organisation,
            profile_snapshot=profile,
            bidder_document_ids=doc_ids,
            compliance_score=compliance_score,
            status="SUBMITTED",
            assessment=assessment,
            summary=summary,
            submitted_at=now_dt,
            updated_at=now_dt,
        )

        try:
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO tender_submissions (
                        submission_id, tender_id, requirement_version,
                        bidder_id, bidder_user_id, bidder_name, bidder_org, bidder_organisation,
                        bidder_profile_json, profile_snapshot_json,
                        bidder_document_ids_json, compliance_score, status, review_status,
                        match_status, analysis_id, result_json, award_justification,
                        assessment_json, summary_json, submitted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sub_id,
                        tender_id,
                        requirement_version,
                        bidder_user_id,
                        bidder_user_id,
                        bidder_organisation,
                        bidder_organisation,
                        bidder_organisation,
                        prof_json,
                        prof_json,
                        docs_json,
                        compliance_score,
                        "SUBMITTED",
                        "SUBMITTED",
                        "COMPLIANT" if compliance_score >= 75.0 else "GAPS",
                        f"ANL-{sub_id}",
                        ass_json,
                        "",
                        ass_json,
                        sum_json,
                        now_iso,
                        now_iso,
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Submission saved to fallback buffer: {exc}")

        _FALLBACK_SUBMISSIONS[sub_id] = sub_obj
        return sub_obj

    def list_submissions_for_tender(self, tender_id: str) -> List[TenderSubmission]:
        """Fetch all bidder submissions filed against a specific tender ID."""
        try:
            with sqlite_connection(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM tender_submissions
                    WHERE tender_id = ?
                    ORDER BY compliance_score DESC, submitted_at ASC
                    """,
                    (tender_id,),
                ).fetchall()
                results: List[TenderSubmission] = []
                for r in rows:
                    r_dict = dict(r)
                    bidder_user_id = r_dict.get("bidder_user_id") or r_dict.get("bidder_id") or ""
                    bidder_org = r_dict.get("bidder_organisation") or r_dict.get("bidder_org") or ""
                    prof_json_str = r_dict.get("profile_snapshot_json") or r_dict.get("bidder_profile_json") or "{}"
                    ass_json_str = r_dict.get("assessment_json") or r_dict.get("result_json") or "[]"
                    sum_json_str = r_dict.get("summary_json") or "{}"

                    try:
                        prof_obj = BidderProfile.model_validate_json(prof_json_str)
                    except Exception:
                        prof_obj = BidderProfile(
                            profile_id=f"PRF-{bidder_user_id}",
                            user_id=bidder_user_id,
                            organisation_name=bidder_org,
                        )

                    try:
                        ass_list = [RequirementAssessment(**a) for a in json.loads(ass_json_str)]
                    except Exception:
                        ass_list = []

                    try:
                        sum_obj = ComplianceSummaryMetrics.model_validate_json(sum_json_str)
                    except Exception:
                        sum_obj = ComplianceSummaryMetrics(
                            total_requirements=0,
                            evidence_found_count=0,
                            missing_count=0,
                            conflicting_count=0,
                            needs_review_count=0,
                            mandatory_gap_count=0,
                            safety_requirements_count=0,
                            overall_readiness_score=float(r_dict.get("compliance_score") or 0.0),
                            by_category={},
                        )

                    doc_ids_raw = r_dict.get("bidder_document_ids_json")
                    doc_ids_list = json.loads(doc_ids_raw) if doc_ids_raw else []

                    sub = TenderSubmission(
                        submission_id=r_dict["submission_id"],
                        tender_id=r_dict["tender_id"],
                        requirement_version=int(r_dict.get("requirement_version") or 1),
                        bidder_user_id=bidder_user_id,
                        bidder_organisation=bidder_org,
                        profile_snapshot=prof_obj,
                        bidder_document_ids=doc_ids_list,
                        compliance_score=float(r_dict.get("compliance_score") or 0.0),
                        status=r_dict.get("status") or r_dict.get("review_status") or "SUBMITTED",
                        assessment=ass_list,
                        summary=sum_obj,
                        submitted_at=datetime.fromisoformat(r_dict["submitted_at"]) if r_dict.get("submitted_at") else datetime.now(timezone.utc),
                        updated_at=datetime.fromisoformat(r_dict["updated_at"]) if r_dict.get("updated_at") else datetime.now(timezone.utc),
                    )
                    results.append(sub)
                    _FALLBACK_SUBMISSIONS[sub.submission_id] = sub
                return results
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying submissions for tender: {exc}")

        return [
            s for s in _FALLBACK_SUBMISSIONS.values() if s.tender_id == tender_id
        ]

    def list_submissions_for_bidder(
        self, bidder_user_id: str
    ) -> List[TenderSubmission]:
        """Fetch all submissions filed by a specific bidder user."""
        try:
            with sqlite_connection(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM tender_submissions
                    WHERE bidder_user_id = ? OR bidder_id = ?
                    ORDER BY submitted_at DESC
                    """,
                    (bidder_user_id, bidder_user_id),
                ).fetchall()
                results: List[TenderSubmission] = []
                for r in rows:
                    r_dict = dict(r)
                    b_user_id = r_dict.get("bidder_user_id") or r_dict.get("bidder_id") or ""
                    b_org = r_dict.get("bidder_organisation") or r_dict.get("bidder_org") or ""
                    prof_json_str = r_dict.get("profile_snapshot_json") or r_dict.get("bidder_profile_json") or "{}"
                    ass_json_str = r_dict.get("assessment_json") or r_dict.get("result_json") or "[]"
                    sum_json_str = r_dict.get("summary_json") or "{}"

                    try:
                        prof_obj = BidderProfile.model_validate_json(prof_json_str)
                    except Exception:
                        prof_obj = BidderProfile(
                            profile_id=f"PRF-{b_user_id}",
                            user_id=b_user_id,
                            organisation_name=b_org,
                        )

                    try:
                        ass_list = [RequirementAssessment(**a) for a in json.loads(ass_json_str)]
                    except Exception:
                        ass_list = []

                    try:
                        sum_obj = ComplianceSummaryMetrics.model_validate_json(sum_json_str)
                    except Exception:
                        sum_obj = ComplianceSummaryMetrics(
                            total_requirements=0,
                            evidence_found_count=0,
                            missing_count=0,
                            conflicting_count=0,
                            needs_review_count=0,
                            mandatory_gap_count=0,
                            safety_requirements_count=0,
                            overall_readiness_score=float(r_dict.get("compliance_score") or 0.0),
                            by_category={},
                        )

                    doc_ids_raw = r_dict.get("bidder_document_ids_json")
                    doc_ids_list = json.loads(doc_ids_raw) if doc_ids_raw else []

                    sub = TenderSubmission(
                        submission_id=r_dict["submission_id"],
                        tender_id=r_dict["tender_id"],
                        requirement_version=int(r_dict.get("requirement_version") or 1),
                        bidder_user_id=b_user_id,
                        bidder_organisation=b_org,
                        profile_snapshot=prof_obj,
                        bidder_document_ids=doc_ids_list,
                        compliance_score=float(r_dict.get("compliance_score") or 0.0),
                        status=r_dict.get("status") or r_dict.get("review_status") or "SUBMITTED",
                        assessment=ass_list,
                        summary=sum_obj,
                        submitted_at=datetime.fromisoformat(r_dict["submitted_at"]) if r_dict.get("submitted_at") else datetime.now(timezone.utc),
                        updated_at=datetime.fromisoformat(r_dict["updated_at"]) if r_dict.get("updated_at") else datetime.now(timezone.utc),
                    )
                    results.append(sub)
                return results
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying submissions for bidder: {exc}")

        return [
            s for s in _FALLBACK_SUBMISSIONS.values() if s.bidder_user_id == bidder_user_id
        ]
