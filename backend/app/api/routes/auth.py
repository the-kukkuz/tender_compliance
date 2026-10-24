"""Authentication endpoints for user registration, login, and current session inspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import AppError, AuthenticationError
from app.core.logging import get_logger, get_request_id
from app.core.security import create_access_token, hash_password, verify_password
from app.models.profile_record import ProfileRepository
from app.models.user_record import UserRepository
from app.schemas.auth import (
    AuthTokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    UserRole,
)
from app.schemas.common import ApiErrorDetail, ApiMeta, ApiResponse, ErrorCode, ProcessingState

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=ApiResponse[AuthTokenResponse], status_code=status.HTTP_201_CREATED)
async def register_user(req: UserRegisterRequest) -> ApiResponse[AuthTokenResponse]:
    """Register a new user account with role specification (SEEKER or ISSUER)."""
    settings = get_settings()
    user_repo = UserRepository(settings.sqlite_db_path)
    profile_repo = ProfileRepository(settings.sqlite_db_path)

    existing = user_repo.get_user_by_email(req.email)
    if existing:
        raise AppError(
            message=f"An account with email '{req.email}' already exists.",
            code=ErrorCode.VALIDATION_ERROR,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=[ApiErrorDetail(field="email", message="Email address is already registered.")],
        )

    pwd_hash = hash_password(req.password)
    user_resp = user_repo.create_user(
        name=req.name,
        email=req.email,
        password_hash=pwd_hash,
        organisation_name=req.organisation_name,
        role=req.role,
    )

    # Initialize default starter profile for seekers or dual accounts
    if req.role in (UserRole.SEEKER, UserRole.BOTH):
        profile_repo.get_or_create_default(user_resp.user_id, user_resp.organisation_name)

    token = create_access_token(
        {
            "sub": user_resp.user_id,
            "email": user_resp.email,
            "role": user_resp.role.value,
            "organisation_name": user_resp.organisation_name,
        }
    )

    return ApiResponse[AuthTokenResponse](
        success=True,
        data=AuthTokenResponse(access_token=token, token_type="bearer", user=user_resp),
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.post("/login", response_model=ApiResponse[AuthTokenResponse])
async def login_user(req: UserLoginRequest) -> ApiResponse[AuthTokenResponse]:
    """Authenticate existing user credentials and return bearer access token."""
    settings = get_settings()
    user_repo = UserRepository(settings.sqlite_db_path)

    user_row = user_repo.get_user_by_email(req.email)
    if not user_row or not verify_password(req.password, user_row["password_hash"]):
        raise AuthenticationError("Invalid email or password.")

    user_role_str = user_row["role"]
    if req.mode:
        requested_mode_str = req.mode.value if isinstance(req.mode, UserRole) else str(req.mode)
        # If user has single role and tries to switch to unauthorized mode
        if user_role_str != UserRole.BOTH.value and user_role_str != requested_mode_str:
            raise AuthenticationError(
                f"Your account is registered as '{user_role_str}' and is not authorized to access '{requested_mode_str}' mode."
            )

    user_resp = UserResponse(
        user_id=user_row["user_id"],
        email=user_row["email"],
        name=user_row["name"],
        organisation_name=user_row["organisation_name"],
        role=UserRole(user_role_str),
        created_at=user_row["created_at"],
    )

    token = create_access_token(
        {
            "sub": user_resp.user_id,
            "email": user_resp.email,
            "role": user_resp.role.value,
            "organisation_name": user_resp.organisation_name,
        }
    )

    return ApiResponse[AuthTokenResponse](
        success=True,
        data=AuthTokenResponse(access_token=token, token_type="bearer", user=user_resp),
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )


@router.get("/me", response_model=ApiResponse[UserResponse])
async def get_my_account(
    current_user: UserResponse = Depends(get_current_user),
) -> ApiResponse[UserResponse]:
    """Retrieve current authenticated user session details."""
    settings = get_settings()
    return ApiResponse[UserResponse](
        success=True,
        data=current_user,
        meta=ApiMeta(
            request_id=get_request_id(),
            processing_state=ProcessingState.COMPLETED,
            version=settings.app_version,
        ),
    )
