"""Bidder profile management and document extraction endpoints."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_current_user, require_role
from app.core.config import get_settings
from app.core.exceptions import InvalidFileTypeError, NotFoundError
from app.core.logging import get_logger, get_request_id
from app.models.document_record import DocumentRepository
from app.models.profile_record import ProfileRepository
from app.schemas.auth import UserResponse, UserRole
from app.schemas.common import ApiMeta, ApiResponse, ProcessingState
from app.schemas.document import DocumentRole
from app.schemas.profile import (
    BidderProfile,
    BidderProfileUpdateRequest,
    ProfileExtractionResponse,
)
from app.services.pdf_extractor import PDFExtractorService
from app.services.profile_extractor import ProfileExtractorService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/profile", tags=["Bidder Profile"])


@router.get("", response_model=ApiResponse[BidderProfile])
async def get_my_bidder_profile(
    current_user: UserResponse = Depends(require_role([UserRole.SEEKER])),
) -> ApiResponse[BidderProfile]:
    """Retrieve the reusable qualification profile for the authenticated tender seeker."""
    settings = get_settings()
    profile_repo = ProfileRepository(settings.sqlite_db_path)

    profile = profile_repo.get_or_create_default(
        user_id=current_user.user_id,
        organisation_name=current_user.organisation_name,
    )

    return ApiResponse[BidderProfile](
        success=True,
        data=profile,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.put("", response_model=ApiResponse[BidderProfile])
async def update_my_bidder_profile(
    updates: BidderProfileUpdateRequest,
    current_user: UserResponse = Depends(require_role([UserRole.SEEKER])),
) -> ApiResponse[BidderProfile]:
    """Update and verify the authenticated seeker's reusable profile data."""
    settings = get_settings()
    profile_repo = ProfileRepository(settings.sqlite_db_path)

    current_profile = profile_repo.get_or_create_default(
        user_id=current_user.user_id,
        organisation_name=current_user.organisation_name,
    )

    if updates.organisation_name is not None:
        current_profile.organisation_name = updates.organisation_name
    if updates.business_identifiers is not None:
        current_profile.business_identifiers = updates.business_identifiers
    if updates.categories is not None:
        current_profile.categories = updates.categories
    if updates.experience_years is not None:
        current_profile.experience_years = updates.experience_years
    if updates.experience_summary is not None:
        current_profile.experience_summary = updates.experience_summary
    if updates.past_projects is not None:
        current_profile.past_projects = updates.past_projects
    if updates.certifications is not None:
        current_profile.certifications = updates.certifications
    if updates.annual_turnover is not None:
        current_profile.annual_turnover = updates.annual_turnover
    if updates.currency is not None:
        current_profile.currency = updates.currency
    if updates.financial_audited is not None:
        current_profile.financial_audited = updates.financial_audited
    if updates.locations is not None:
        current_profile.locations = updates.locations
    if updates.safety_manual_approved is not None:
        current_profile.safety_manual_approved = updates.safety_manual_approved
    if updates.other_qualifications is not None:
        current_profile.other_qualifications = updates.other_qualifications
    if updates.supporting_document_ids is not None:
        current_profile.supporting_document_ids = updates.supporting_document_ids
    if updates.is_verified is not None:
        current_profile.is_verified = updates.is_verified

    saved = profile_repo.save_profile(current_profile)

    return ApiResponse[BidderProfile](
        success=True,
        data=saved,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.post("/upload-and-extract", response_model=ApiResponse[ProfileExtractionResponse])
async def upload_and_extract_profile(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(require_role([UserRole.SEEKER])),
) -> ApiResponse[ProfileExtractionResponse]:
    """Upload a company profile/capability PDF and extract structured fields for review."""
    settings = get_settings()
    pdf_extractor = PDFExtractorService(settings)
    doc_repo = DocumentRepository(settings.sqlite_db_path)
    extractor_service = ProfileExtractorService()

    content_bytes = await file.read()
    if not content_bytes:
        raise InvalidFileTypeError("Uploaded file is empty.")

    doc_id = f"DOC-PROF-{uuid.uuid4().hex[:6].upper()}"
    filename = file.filename or "bidder_profile.pdf"

    extracted_doc = pdf_extractor.extract_from_bytes(
        document_id=doc_id,
        filename=filename,
        content_bytes=content_bytes,
        role=DocumentRole.BIDDER_SUPPORTING,
    )
    doc_repo.save_document(extracted_doc)

    extraction_res = extractor_service.extract_profile_from_document(
        doc_extraction=extracted_doc,
        user_id=current_user.user_id,
        default_org_name=current_user.organisation_name,
    )

    return ApiResponse[ProfileExtractionResponse](
        success=True,
        data=extraction_res,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
            warnings=extracted_doc.extraction_warnings,
        ),
    )
