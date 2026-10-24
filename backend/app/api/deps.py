"""FastAPI dependencies for authentication, role authorization, and tenant isolation."""

from __future__ import annotations

from typing import Callable, List, Optional

from fastapi import Depends, Header, Request

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ForbiddenError
from app.core.security import decode_access_token
from app.models.user_record import UserRepository
from app.schemas.auth import UserResponse, UserRole


def _extract_bearer_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Extract bearer token from Authorization header."""
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def get_optional_current_user(
    token: Optional[str] = Depends(_extract_bearer_token),
) -> Optional[UserResponse]:
    """Resolve current user if a valid bearer token is present, without failing."""
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None

    settings = get_settings()
    user_repo = UserRepository(settings.sqlite_db_path)
    return user_repo.get_user_by_id(payload["sub"])


async def get_current_user(
    token: Optional[str] = Depends(_extract_bearer_token),
) -> UserResponse:
    """Validate bearer token and resolve authenticated user, raising 401 if invalid."""
    if not token:
        raise AuthenticationError("Authorization header with Bearer token is required.")

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise AuthenticationError("Invalid or expired session token. Please log in again.")

    settings = get_settings()
    user_repo = UserRepository(settings.sqlite_db_path)
    user = user_repo.get_user_by_id(payload["sub"])
    if not user:
        raise AuthenticationError("User account not found or session terminated.")

    return user


def require_role(allowed_roles: List[UserRole | str]) -> Callable:
    """Dependency factory checking that the user possesses an authorized role."""
    allowed_str_set = {
        r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles
    }
    # Always permit dual-mode BOTH accounts
    allowed_str_set.add(UserRole.BOTH.value)

    async def _role_checker(
        current_user: UserResponse = Depends(get_current_user),
    ) -> UserResponse:
        user_role_str = current_user.role.value
        if user_role_str not in allowed_str_set:
            raise ForbiddenError(
                f"Action requires one of [{', '.join(allowed_str_set)}], but current role is {user_role_str}."
            )
        return current_user

    return _role_checker
