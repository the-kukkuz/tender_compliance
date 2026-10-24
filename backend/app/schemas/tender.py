"""Tender publication, requirement versioning, matching, and bidder submission schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.compliance import (
    ComplianceSummaryMetrics,
    RequirementAssessment,
    TenderRequirement,
)
from app.schemas.profile import BidderProfile


class TenderStatus(str, Enum):
    """Lifecycle status of a tender record."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class TenderCreateRequest(BaseModel):
    """Payload to confirm and publish a tender after single-document extraction review."""

    title: str = Field(..., min_length=3, description="Tender title.")
    description: str = Field(..., min_length=5, description="Brief description or scope of work.")
    category: str = Field(..., min_length=2, description="Tender category / sector.")
    submission_deadline: str = Field(
        ..., description="Submission deadline in YYYY-MM-DD format."
    )
    financial_threshold: Optional[float] = Field(
        default=None, ge=0.0, description="Minimum financial turnover or threshold required."
    )
    financial_currency: Optional[str] = Field(
        default="USD", description="Currency of financial threshold."
    )
    geographic_restrictions: List[str] = Field(
        default_factory=list, description="Eligible regions or geographical boundaries."
    )
    required_certifications: List[str] = Field(
        default_factory=list, description="Specific certifications required (e.g., ISO 9001, ISO 45001)."
    )
    min_experience_years: Optional[float] = Field(
        default=0.0, ge=0.0, description="Minimum years of operating experience."
    )
    safety_requirements: List[str] = Field(
        default_factory=list, description="Specific safety, HSE, or work-permit conditions."
    )
    required_documents: List[str] = Field(
        default_factory=list, description="List of mandatory supporting documents required."
    )
    document_id: str = Field(
        ..., description="Document ID of the single uploaded tender PDF."
    )
    extracted_requirements: List[TenderRequirement] = Field(
        default_factory=list, description="Authoritative structured requirements list."
    )


class TenderUpdateRequest(BaseModel):
    """Payload to update an existing tender's details or requirements."""

    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    submission_deadline: Optional[str] = None
    financial_threshold: Optional[float] = None
    financial_currency: Optional[str] = None
    geographic_restrictions: Optional[List[str]] = None
    required_certifications: Optional[List[str]] = None
    min_experience_years: Optional[float] = None
    safety_requirements: Optional[List[str]] = None
    required_documents: Optional[List[str]] = None
    status: Optional[TenderStatus] = None
    extracted_requirements: Optional[List[TenderRequirement]] = None


class TenderResponse(BaseModel):
    """Full tender record returned from the database."""

    tender_id: str
    issuer_user_id: str
    issuer_organisation: str
    title: str
    description: str
    category: str
    status: TenderStatus
    submission_deadline: str
    financial_threshold: Optional[float] = None
    financial_currency: Optional[str] = "USD"
    geographic_restrictions: List[str] = Field(default_factory=list)
    required_certifications: List[str] = Field(default_factory=list)
    min_experience_years: Optional[float] = 0.0
    safety_requirements: List[str] = Field(default_factory=list)
    required_documents: List[str] = Field(default_factory=list)
    document_id: str
    extracted_requirements: List[TenderRequirement] = Field(default_factory=list)
    requirement_version: int = 1
    created_at: datetime
    updated_at: datetime


class TenderDraftExtractionResponse(BaseModel):
    """Candidate structured tender data extracted from one uploaded PDF for issuer review."""

    document_id: str
    filename: str
    extracted_tender: TenderCreateRequest
    review_notes: List[str] = Field(default_factory=list)


class TenderMatchSummary(BaseModel):
    """Ranked tender match result evaluated against a bidder's saved profile."""

    tender: TenderResponse
    compliance_score: float
    has_mandatory_gaps: bool
    mandatory_satisfied_count: int
    mandatory_total_count: int
    optional_satisfied_count: int
    optional_total_count: int
    missing_mandatory_titles: List[str] = Field(default_factory=list)
    conflicting_items: List[str] = Field(default_factory=list)
    supporting_evidence_count: int = 0
    match_explanation: str
    days_remaining: int
    next_action: str
    sorting_rule: str
    disclaimer: str
    requirement_assessments: Optional[List[RequirementAssessment]] = None


class TenderSubmission(BaseModel):
    """Bidder submission linked to a specific tender and requirement version."""

    submission_id: str
    tender_id: str
    requirement_version: int
    bidder_user_id: str
    bidder_organisation: str
    profile_snapshot: BidderProfile
    bidder_document_ids: List[str] = Field(default_factory=list)
    compliance_score: float
    status: str = "SUBMITTED"
    assessment: List[RequirementAssessment] = Field(default_factory=list)
    summary: ComplianceSummaryMetrics
    submitted_at: datetime
    updated_at: datetime


class IssuerTenderSummary(BaseModel):
    """Summary of an issuer's tender including submission analytics."""

    tender: TenderResponse
    submission_count: int
    compliant_submissions_count: int
    submissions_with_gaps_count: int
    avg_compliance_score: float


class BidderComparisonRow(BaseModel):
    """A row in the issuer's bidder comparison matrix for a specific tender."""

    submission_id: str
    tender_id: str
    requirement_version: int
    bidder_organisation: str
    compliance_score: float
    mandatory_satisfied: str
    missing_evidence: List[str] = Field(default_factory=list)
    conflicting_evidence: List[str] = Field(default_factory=list)
    submission_date: str
    status: str
    assessment: List[RequirementAssessment] = Field(default_factory=list)
