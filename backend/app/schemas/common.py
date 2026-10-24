"""Common API envelopes, error contracts, and processing state schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

DECISION_SUPPORT_DISCLAIMER = (
    "Bid2Work AI is a decision-support intelligence tool. It does not constitute "
    "automated legal eligibility determination, formal tender adjudication, or "
    "an official work-permit issuance system. All findings must be verified by "
    "qualified procurement, legal, and HSE personnel."
)


class ProcessingState(str, Enum):
    """Lifecycle states for document extraction, compliance analysis, and permit readiness."""

    IDLE = "IDLE"
    UPLOADING = "UPLOADING"
    EXTRACTING = "EXTRACTING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ErrorCode(str, Enum):
    """Standardized API error codes."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UPLOAD_LIMIT_EXCEEDED = "UPLOAD_LIMIT_EXCEEDED"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    PDF_EXTRACTION_ERROR = "PDF_EXTRACTION_ERROR"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiErrorDetail(BaseModel):
    """Granular error detail for field or document validation issues."""

    field: Optional[str] = Field(
        default=None, description="Field or parameter name associated with the error."
    )
    message: str = Field(..., description="Human-readable detail message.")
    code: Optional[str] = Field(default=None, description="Specific sub-error identifier.")


class ApiError(BaseModel):
    """Structured error object returned when an API call fails."""

    code: ErrorCode = Field(..., description="Machine-readable error code.")
    message: str = Field(..., description="High-level summary of the error.")
    details: List[ApiErrorDetail] = Field(
        default_factory=list, description="Optional list of granular validation or processing errors."
    )
    request_id: str = Field(default="-", description="Correlation request ID for log tracing.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the error occurred.",
    )


class ApiMeta(BaseModel):
    """Metadata attached to every API response."""

    request_id: str = Field(default="-", description="Request trace identifier.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of response generation.",
    )
    processing_state: ProcessingState = Field(
        default=ProcessingState.COMPLETED,
        description="Current processing state for the operation.",
    )
    version: str = Field(default="0.1.0", description="API contract version.")
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings produced during processing.",
    )


class ApiResponse(BaseModel, Generic[T]):
    """Consistent API response envelope across all Bid2Work AI endpoints."""

    success: bool = Field(..., description="True if the request succeeded without fatal error.")
    data: Optional[T] = Field(default=None, description="Response payload when success is True.")
    error: Optional[ApiError] = Field(
        default=None, description="Structured error details when success is False."
    )
    meta: ApiMeta = Field(default_factory=ApiMeta, description="Response metadata and warnings.")


class HealthStatus(BaseModel):
    """Service health and readiness payload."""

    status: str = Field(default="healthy", description="Overall service status.")
    service: str = Field(..., description="Application name.")
    version: str = Field(..., description="Application version.")
    environment: str = Field(..., description="Runtime environment name.")
    llm_enabled: bool = Field(
        default=False, description="Whether live LLM API mode is enabled."
    )
    llm_configured: bool = Field(
        ..., description="Whether an external LLM API key is configured."
    )
    llm_provider: str = Field(..., description="Configured LLM provider identifier.")
    llm_model: str = Field(..., description="Configured LLM model name.")
    database_ready: bool = Field(
        ..., description="Whether the SQLite audit database is reachable."
    )
    max_upload_size_mb: int = Field(..., description="Configured upload size limit in MB.")
    max_bidder_files: int = Field(..., description="Configured maximum bidder PDF count.")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC health check timestamp.",
    )
