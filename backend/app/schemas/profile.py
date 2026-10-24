"""Bidder profile schemas and evidence representations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BusinessIdentifier(BaseModel):
    """Business registration, tax, or commercial trade identifier."""

    id_type: str = Field(..., description="e.g., Tax Identification Number, Commercial Registration (CR), DUNS")
    value: str = Field(..., description="The registration number or identifier value.")


class CertificationItem(BaseModel):
    """Accredited certificate held by the bidder organization."""

    name: str = Field(..., description="Certificate name, e.g., ISO 9001:2015, ISO 45001, ASME.")
    cert_number: Optional[str] = Field(default=None, description="Official certificate or license number.")
    valid_until: Optional[str] = Field(default=None, description="Expiry date in YYYY-MM-DD format.")
    accredited_by: Optional[str] = Field(default=None, description="Accreditation body or registrar.")


class PastProjectItem(BaseModel):
    """Past completed project track record item."""

    title: str = Field(..., description="Project title or contract scope.")
    client: str = Field(..., description="Client or procuring entity name.")
    value: Optional[float] = Field(default=None, description="Contract or project value.")
    currency: Optional[str] = Field(default="USD", description="Currency of contract value.")
    completion_year: Optional[int] = Field(default=None, description="Year of successful completion.")


class BidderProfile(BaseModel):
    """Single reusable bidder qualification profile used for matching against published tenders."""

    profile_id: str
    user_id: str
    organisation_name: str
    business_identifiers: List[BusinessIdentifier] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    experience_years: float = Field(default=0.0, ge=0.0)
    experience_summary: str = Field(default="")
    past_projects: List[PastProjectItem] = Field(default_factory=list)
    certifications: List[CertificationItem] = Field(default_factory=list)
    annual_turnover: float = Field(default=0.0, ge=0.0)
    currency: str = Field(default="USD")
    financial_audited: bool = Field(default=True)
    locations: List[str] = Field(default_factory=list)
    safety_manual_approved: bool = Field(default=True)
    other_qualifications: List[str] = Field(default_factory=list)
    supporting_document_ids: List[str] = Field(default_factory=list)
    is_verified: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BidderProfileUpdateRequest(BaseModel):
    """Update payload for modifying verified bidder profile data."""

    organisation_name: Optional[str] = None
    business_identifiers: Optional[List[BusinessIdentifier]] = None
    categories: Optional[List[str]] = None
    experience_years: Optional[float] = Field(default=None, ge=0.0)
    experience_summary: Optional[str] = None
    past_projects: Optional[List[PastProjectItem]] = None
    certifications: Optional[List[CertificationItem]] = None
    annual_turnover: Optional[float] = Field(default=None, ge=0.0)
    currency: Optional[str] = None
    financial_audited: Optional[bool] = None
    locations: Optional[List[str]] = None
    safety_manual_approved: Optional[bool] = None
    other_qualifications: Optional[List[str]] = None
    supporting_document_ids: Optional[List[str]] = None
    is_verified: Optional[bool] = None


class ProfileExtractionResponse(BaseModel):
    """Extracted profile draft returned for user review and correction."""

    document_id: str
    filename: str
    extracted_profile: BidderProfile
    review_notes: List[str] = Field(default_factory=list)
