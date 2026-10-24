"""Tender publication, requirement review, discovery, compliance matching, and submission routes."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import get_current_user, get_optional_current_user, require_role
from app.core.config import get_settings
from app.core.exceptions import AppError, ForbiddenError, InvalidFileTypeError, NotFoundError
from app.core.logging import get_logger, get_request_id
from app.models.document_record import DocumentRepository
from app.models.profile_record import ProfileRepository
from app.models.tender_record import TenderRepository
from app.schemas.auth import UserResponse, UserRole
from app.schemas.common import ApiErrorDetail, ApiMeta, ApiResponse, ErrorCode, ProcessingState
from app.schemas.compliance import (
    RequirementCategory,
    RequirementPriority,
    SourceReference,
    TenderRequirement,
)
from app.schemas.document import DocumentRole
from app.schemas.tender import (
    BidderComparisonRow,
    IssuerTenderSummary,
    TenderCreateRequest,
    TenderDraftExtractionResponse,
    TenderMatchSummary,
    TenderResponse,
    TenderStatus,
    TenderSubmission,
    TenderUpdateRequest,
)
from app.services.pdf_extractor import PDFExtractorService
from app.services.requirement_extractor import RequirementExtractorService
from app.services.tender_matcher import TenderMatcherService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/tenders", tags=["Tenders"])

_MONEY_REGEX = re.compile(
    r"\b((?:Rs\.?|INR|USD|EUR|GBP|\$|€|£)\s*[\d,.]+(?:\s*(?:Crores?|Lakhs?|M|million|k|thousand|B|billion|/-))?|[\d,.]+\s*(?:Crores?|Lakhs?|M|million|k|thousand|B|billion)\s*(?:Rs\.?|INR|USD|EUR|GBP)?)\b",
    re.IGNORECASE,
)
_DATE_REGEX = re.compile(r"\b(\d{2}[./-]\d{2}[./-]\d{4}|20\d{2}-\d{2}-\d{2})\b")


def _parse_money_val(raw_text: str) -> tuple[Optional[float], str]:
    if not raw_text:
        return None, "USD"
    curr = "USD"
    raw_upper = raw_text.upper()
    if "€" in raw_text or "EUR" in raw_upper:
        curr = "EUR"
    elif "£" in raw_text or "GBP" in raw_upper:
        curr = "GBP"
    elif "RS" in raw_upper or "INR" in raw_upper or "/-" in raw_text:
        curr = "INR"

    match = re.search(r"([\d,.]+)\s*(Crores?|Lakhs?|M|million|k|thousand|B|billion)?", raw_text, re.IGNORECASE)
    if not match:
        return None, curr

    num_str = match.group(1).replace(",", "").rstrip(".")
    unit = (match.group(2) or "").lower()
    try:
        val = float(num_str)
        if unit in ("crore", "crores"):
            val *= 10_000_000
        elif unit in ("lakh", "lakhs"):
            val *= 100_000
        elif unit in ("m", "million"):
            val *= 1_000_000
        elif unit in ("k", "thousand"):
            val *= 1_000
        elif unit in ("b", "billion"):
            val *= 1_000_000_000
        return val, curr
    except ValueError:
        return None, curr


@router.post("/upload-and-extract", response_model=ApiResponse[TenderDraftExtractionResponse])
async def upload_and_extract_tender(
    tender_file: UploadFile = File(...),
    current_user: UserResponse = Depends(require_role([UserRole.ISSUER])),
) -> ApiResponse[TenderDraftExtractionResponse]:
    """Upload one tender PDF, extract text and candidate requirements for issuer review."""
    settings = get_settings()
    pdf_extractor = PDFExtractorService(settings)
    doc_repo = DocumentRepository(settings.sqlite_db_path)
    req_extractor = RequirementExtractorService(settings=settings)

    content_bytes = await tender_file.read()
    if not content_bytes:
        raise InvalidFileTypeError("Uploaded tender file is empty.")

    doc_id = f"DOC-TND-{uuid.uuid4().hex[:6].upper()}"
    filename = tender_file.filename or "tender_document.pdf"

    extracted_doc = pdf_extractor.extract_from_bytes(
        document_id=doc_id,
        filename=filename,
        content_bytes=content_bytes,
        role=DocumentRole.TENDER,
    )
    doc_repo.save_document(extracted_doc)

    # 1. Extract requirements
    if settings.llm_enabled:
        extracted_reqs = await req_extractor.extract_requirements_async(extracted_doc)
    else:
        extracted_reqs = req_extractor.extract_requirements(extracted_doc)

    full_text = " ".join(p.text for p in extracted_doc.pages if p.text)
    review_notes: List[str] = []

    # 2. Extract Title
    title = f"Tender: {filename.replace('.pdf', '').replace('_', ' ').title()}"
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]
    for line in lines[:8]:
        if len(line) > 10 and not any(kw in line.lower() for kw in ("page", "table", "section", "clause")):
            if any(kw in line.lower() for kw in ("tender", "request for", "rfp", "contract", "invitation", "works")):
                title = line
                break

    # 3. Category inference
    category = "CONSTRUCTION"
    lower_text = full_text.lower()
    if "safety" in lower_text or "hse" in lower_text:
        category = "SAFETY & HSE"
    elif "engineering" in lower_text or "mechanical" in lower_text:
        category = "ENGINEERING"
    elif "it" in lower_text or "software" in lower_text:
        category = "IT & SOFTWARE"
    elif "energy" in lower_text or "oil" in lower_text:
        category = "ENERGY & RESOURCES"

    # 4. Financial threshold
    money_matches = _MONEY_REGEX.findall(full_text)
    threshold = 5000000.0
    currency = "USD"
    if money_matches:
        for m in money_matches:
            val, curr = _parse_money_val(m)
            if val and val >= 100000:
                threshold = val
                currency = curr
                break
    else:
        review_notes.append("Financial threshold was not explicitly found in document; verify amount.")

    # 5. Submission deadline
    dates_found = _DATE_REGEX.findall(full_text)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    normalized_dates: List[str] = []
    for d in dates_found:
        if "-" in d and len(d.split("-")[0]) == 4:
            normalized_dates.append(d)
        else:
            # Parse DD.MM.YYYY or DD/MM/YYYY
            sep = "." if "." in d else ("/" if "/" in d else "-")
            parts = d.split(sep)
            if len(parts) == 3 and len(parts[2]) == 4:
                normalized_dates.append(f"{parts[2]}-{parts[1]}-{parts[0]}")

    future_dates = [d for d in normalized_dates if d >= today_str]
    deadline = future_dates[0] if future_dates else (normalized_dates[-1] if normalized_dates else "2026-12-31")
    if not future_dates:
        review_notes.append("Submission deadline was parsed from document; please review and confirm.")

    # 6. Certifications
    required_certs = ["ISO 9001"]
    if "iso 14001" in lower_text or "14001" in lower_text:
        required_certs.append("ISO 14001")
    if "iso 45001" in lower_text or "45001" in lower_text:
        required_certs.append("ISO 45001")

    # 7. Safety conditions
    safety_conditions = [
        "Approved Site Safety Plan and Corporate HSE Manual",
        "Mandatory Work-Permit and Risk Assessment Compliance",
    ]
    if "ehs" in lower_text or "eshs" in lower_text:
        safety_conditions.append("Environmental, Social, Health and Safety (ESHS) Works & QAP")

    # 8. Required documents
    req_docs = [
        "Certificate of Incorporation / Trade License",
        "Audited Financial Statements (Last 3 to 5 Years)",
        "Accredited ISO 9001 & 14001 Certificates",
        "Past Project Client Completion Certificates (Last 7 Years)",
    ]
    if "pan" in lower_text:
        req_docs.append("Permanent Account Number (PAN) Card")
    if "gst" in lower_text:
        req_docs.append("Goods & Services Tax (GST) Registration")
    if "emd" in lower_text or "earnest money" in lower_text:
        req_docs.append("Earnest Money Deposit (EMD) Bank Guarantee / Receipt")
    if "integrity pact" in lower_text:
        req_docs.append("Signed & Notarized Integrity Pact (Annexure-VII)")

    geo = ["National", "Regional"]
    if "tamil nadu" in lower_text:
        geo = ["Tamil Nadu", "South India", "National"]

    draft_tender = TenderCreateRequest(
        title=title,
        description=f"Comprehensive procurement contract issued by {current_user.organisation_name}.",
        category=category,
        submission_deadline=deadline,
        financial_threshold=threshold,
        financial_currency=currency,
        geographic_restrictions=geo,
        required_certifications=required_certs,
        min_experience_years=7.0 if "7 years" in lower_text or "seven years" in lower_text else 5.0,
        safety_requirements=safety_conditions,
        required_documents=req_docs,
        document_id=doc_id,
        extracted_requirements=extracted_reqs,
    )

    return ApiResponse[TenderDraftExtractionResponse](
        success=True,
        data=TenderDraftExtractionResponse(
            document_id=doc_id,
            filename=filename,
            extracted_tender=draft_tender,
            review_notes=review_notes,
        ),
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
            warnings=extracted_doc.extraction_warnings,
        ),
    )


@router.post("", response_model=ApiResponse[TenderResponse], status_code=status.HTTP_201_CREATED)
async def publish_tender(
    create_req: TenderCreateRequest,
    current_user: UserResponse = Depends(require_role([UserRole.ISSUER])),
) -> ApiResponse[TenderResponse]:
    """Confirm reviewed requirements and publish authoritative tender record."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)

    # Validate essential requirements
    if not create_req.title or len(create_req.title.strip()) < 3:
        raise AppError("Tender title is required.", ErrorCode.VALIDATION_ERROR, 400)

    try:
        deadline_dt = date.fromisoformat(create_req.submission_deadline)
    except ValueError:
        raise AppError(
            "Submission deadline must be a valid ISO date string (YYYY-MM-DD).",
            ErrorCode.VALIDATION_ERROR,
            400,
        )

    if not create_req.extracted_requirements:
        raise AppError(
            "At least one structured requirement must be confirmed before publishing a tender.",
            ErrorCode.VALIDATION_ERROR,
            400,
        )

    tender = tender_repo.create_tender(
        issuer_user_id=current_user.user_id,
        issuer_organisation=current_user.organisation_name,
        create_req=create_req,
    )

    return ApiResponse[TenderResponse](
        success=True,
        data=tender,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.get("/my", response_model=ApiResponse[List[IssuerTenderSummary]])
async def list_my_tenders(
    current_user: UserResponse = Depends(require_role([UserRole.ISSUER])),
) -> ApiResponse[List[IssuerTenderSummary]]:
    """List existing tenders issued by the authenticated organisation with submission stats."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)

    tenders = tender_repo.list_tenders_by_issuer(current_user.user_id)
    summaries: List[IssuerTenderSummary] = []

    for t in tenders:
        subs = tender_repo.list_submissions_for_tender(t.tender_id)
        sub_count = len(subs)
        comp_count = sum(1 for s in subs if s.compliance_score >= 75.0)
        gap_count = sum(1 for s in subs if s.compliance_score < 75.0)
        avg_score = (
            round(sum(s.compliance_score for s in subs) / sub_count, 1)
            if sub_count > 0
            else 0.0
        )

        summaries.append(
            IssuerTenderSummary(
                tender=t,
                submission_count=sub_count,
                compliant_submissions_count=comp_count,
                submissions_with_gaps_count=gap_count,
                avg_compliance_score=avg_score,
            )
        )

    return ApiResponse[List[IssuerTenderSummary]](
        success=True,
        data=summaries,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.get("/search", response_model=ApiResponse[List[TenderMatchSummary]])
async def search_and_match_tenders(
    category: Optional[str] = Query(None, description="Filter by category"),
    max_threshold: Optional[float] = Query(None, description="Max required turnover"),
    location: Optional[str] = Query(None, description="Location match"),
    required_cert: Optional[str] = Query(None, description="Required certification"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: UserResponse = Depends(require_role([UserRole.SEEKER])),
) -> ApiResponse[List[TenderMatchSummary]]:
    """Retrieve all published eligible tenders and rank by compliance against bidder profile."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)
    profile_repo = ProfileRepository(settings.sqlite_db_path)
    matcher = TenderMatcherService()

    profile = profile_repo.get_or_create_default(
        user_id=current_user.user_id,
        organisation_name=current_user.organisation_name,
    )

    # Retrieve all published tenders
    all_tenders, _ = tender_repo.list_published_tenders(limit=500)

    # Match and rank with tie-breakers and pagination
    paginated_matches, total_count = matcher.match_all_tenders(
        tenders=all_tenders,
        profile=profile,
        category_filter=category,
        max_financial_threshold=max_threshold,
        location_filter=location,
        required_cert_filter=required_cert,
        page=page,
        page_size=page_size,
    )

    return ApiResponse[List[TenderMatchSummary]](
        success=True,
        data=paginated_matches,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
            warnings=[f"Total eligible tenders evaluated: {total_count}"],
        ),
    )


@router.get("/submissions/my", response_model=ApiResponse[List[TenderSubmission]])
async def list_my_submissions(
    current_user: UserResponse = Depends(require_role([UserRole.SEEKER])),
) -> ApiResponse[List[TenderSubmission]]:
    """List all tender applications submitted by the current seeker organisation."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)

    submissions = tender_repo.list_submissions_for_bidder(current_user.user_id)
    return ApiResponse[List[TenderSubmission]](
        success=True,
        data=submissions,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.get("/{tender_id}", response_model=ApiResponse[TenderResponse])
async def get_tender_by_id(
    tender_id: str,
    current_user: Optional[UserResponse] = Depends(get_optional_current_user),
) -> ApiResponse[TenderResponse]:
    """Retrieve tender details by tender_id."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)

    tender = tender_repo.get_tender(tender_id)
    if not tender:
        raise NotFoundError(f"Tender '{tender_id}' not found.")

    # Cross-organisation isolation: DRAFT tenders only visible to issuer
    if tender.status != TenderStatus.PUBLISHED:
        if not current_user or current_user.user_id != tender.issuer_user_id:
            raise ForbiddenError("Private tender is not accessible.")

    return ApiResponse[TenderResponse](
        success=True,
        data=tender,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.put("/{tender_id}", response_model=ApiResponse[TenderResponse])
async def update_tender(
    tender_id: str,
    updates: TenderUpdateRequest,
    current_user: UserResponse = Depends(require_role([UserRole.ISSUER])),
) -> ApiResponse[TenderResponse]:
    """Update tender requirements and increment version history (owner only)."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)

    tender = tender_repo.get_tender(tender_id)
    if not tender:
        raise NotFoundError(f"Tender '{tender_id}' not found.")

    if tender.issuer_user_id != current_user.user_id:
        raise ForbiddenError("You cannot modify tenders issued by another organisation.")

    updated = tender_repo.update_tender(tender_id, updates)
    return ApiResponse[TenderResponse](
        success=True,
        data=updated,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.post("/{tender_id}/apply", response_model=ApiResponse[TenderSubmission])
async def apply_to_tender(
    tender_id: str,
    current_user: UserResponse = Depends(require_role([UserRole.SEEKER])),
) -> ApiResponse[TenderSubmission]:
    """Submit saved verified bidder profile against a specific tender ID and version."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)
    profile_repo = ProfileRepository(settings.sqlite_db_path)
    matcher = TenderMatcherService()

    tender = tender_repo.get_tender(tender_id)
    if not tender:
        raise NotFoundError(f"Tender '{tender_id}' not found.")

    if tender.status != TenderStatus.PUBLISHED:
        raise AppError("Tender is not open for submissions.", ErrorCode.VALIDATION_ERROR, 400)

    profile = profile_repo.get_or_create_default(
        user_id=current_user.user_id,
        organisation_name=current_user.organisation_name,
    )

    (
        assessments,
        summary,
        has_gaps,
        missing_mandatory,
        conflicts,
    ) = matcher.evaluate_tender_against_profile(tender, profile)

    mandatory_items = [
        a for a in assessments if a.requirement.priority == RequirementPriority.MANDATORY
    ]
    mandatory_satisfied = sum(
        1 for a in mandatory_items if a.status.value == "Evidence Found"
    )
    mandatory_total = len(mandatory_items)

    mand_ratio = (mandatory_satisfied / mandatory_total) if mandatory_total > 0 else 1.0
    optional_items = [
        a for a in assessments if a.requirement.priority != RequirementPriority.MANDATORY
    ]
    opt_ratio = (
        (sum(1 for a in optional_items if a.status.value == "Evidence Found") / len(optional_items))
        if optional_items
        else 1.0
    )

    raw_score = round((mand_ratio * 80.0) + (opt_ratio * 20.0), 1)
    final_score = min(raw_score, 74.9) if has_gaps else raw_score

    submission = tender_repo.create_submission(
        tender_id=tender.tender_id,
        requirement_version=tender.requirement_version,
        bidder_user_id=current_user.user_id,
        bidder_organisation=current_user.organisation_name,
        profile=profile,
        compliance_score=final_score,
        assessment=assessments,
        summary=summary,
    )

    return ApiResponse[TenderSubmission](
        success=True,
        data=submission,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.get("/{tender_id}/submissions", response_model=ApiResponse[List[BidderComparisonRow]])
async def get_tender_submissions_comparison(
    tender_id: str,
    current_user: UserResponse = Depends(require_role([UserRole.ISSUER])),
) -> ApiResponse[List[BidderComparisonRow]]:
    """Retrieve bidder comparison matrix for a specific tender (issuing organisation only)."""
    settings = get_settings()
    tender_repo = TenderRepository(settings.sqlite_db_path)

    tender = tender_repo.get_tender(tender_id)
    if not tender:
        raise NotFoundError(f"Tender '{tender_id}' not found.")

    # Cross-organisation isolation
    if tender.issuer_user_id != current_user.user_id:
        raise ForbiddenError("You cannot review submissions for another organisation's tender.")

    submissions = tender_repo.list_submissions_for_tender(tender_id)
    rows: List[BidderComparisonRow] = []

    for sub in submissions:
        mand_reqs = [
            a for a in sub.assessment if a.requirement.priority == RequirementPriority.MANDATORY
        ]
        mand_sat = sum(1 for a in mand_reqs if a.status.value == "Evidence Found")
        mand_tot = len(mand_reqs)
        mand_str = f"{mand_sat}/{mand_tot}" if mand_tot > 0 else "N/A"

        missing = [
            a.requirement.title
            for a in sub.assessment
            if a.status.value == "Missing"
        ]
        conflicts = [
            f"{a.requirement.title}: {', '.join(a.discrepancies)}"
            for a in sub.assessment
            if a.status.value == "Conflicting"
        ]

        rows.append(
            BidderComparisonRow(
                submission_id=sub.submission_id,
                tender_id=sub.tender_id,
                requirement_version=sub.requirement_version,
                bidder_organisation=sub.bidder_organisation,
                compliance_score=sub.compliance_score,
                mandatory_satisfied=mand_str,
                missing_evidence=missing,
                conflicting_evidence=conflicts,
                submission_date=sub.submitted_at.strftime("%Y-%m-%d %H:%M"),
                status=sub.status,
                assessment=sub.assessment,
            )
        )

    return ApiResponse[List[BidderComparisonRow]](
        success=True,
        data=rows,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )
