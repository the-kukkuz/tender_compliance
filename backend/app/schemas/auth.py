"""Authentication and user management schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class UserRole(str, Enum):
    """Supported user roles in Bid2Work AI."""

    SEEKER = "SEEKER"  # Find Tenders mode
    ISSUER = "ISSUER"  # Publish a Tender mode
    BOTH = "BOTH"      # Dual-mode account

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            v_upper = value.strip().upper()
            for member in cls:
                if member.value == v_upper or member.name == v_upper:
                    return member
        return super()._missing_(value)


class UserRegisterRequest(BaseModel):
    """User registration payload."""

    name: str = Field(..., min_length=2, max_length=100, description="Full name of the user.")
    email: str = Field(..., min_length=5, max_length=150, description="User's email address.")
    password: str = Field(..., min_length=6, max_length=100, description="Account password (min 6 chars).")
    organisation_name: str = Field(
        ..., min_length=2, max_length=150, description="Legal name of the business or organisation."
    )
    role: UserRole = Field(
        default=UserRole.SEEKER, description="Initial mode/role: SEEKER or ISSUER."
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean:
            raise ValueError("Invalid email address format.")
        return clean

    @field_validator("name", "organisation_name")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Field cannot be blank.")
        return clean


class UserLoginRequest(BaseModel):
    """User login payload."""

    email: str = Field(..., description="User's email address.")
    password: str = Field(..., description="Account password.")
    mode: Optional[UserRole] = Field(
        default=None, description="Optional target mode (SEEKER or ISSUER)."
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserResponse(BaseModel):
    """Sanitized user record without sensitive password hashes."""

    user_id: str
    email: str
    name: str
    organisation_name: str
    role: UserRole
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuthTokenResponse(BaseModel):
    """Response returned upon successful authentication."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse
