"""Repository for persisting and retrieving User accounts."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.logging import get_logger
from app.db.sqlite import init_sqlite_db, sqlite_connection
from app.schemas.auth import UserResponse, UserRole

logger = get_logger(__name__)

_FALLBACK_USERS: Dict[str, dict] = {}


class UserRepository:
    """Manages storage and query of authenticated users."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        init_sqlite_db(self.db_path)

    def create_user(
        self,
        name: str,
        email: str,
        password_hash: str,
        organisation_name: str,
        role: UserRole = UserRole.SEEKER,
    ) -> UserResponse:
        """Create and persist a new user record."""
        user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        user_dict = {
            "user_id": user_id,
            "email": email.strip().lower(),
            "password_hash": password_hash,
            "name": name.strip(),
            "organisation_name": organisation_name.strip(),
            "role": role.value if isinstance(role, UserRole) else str(role),
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        try:
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO users (
                        user_id, email, password_hash, name, full_name,
                        organisation_name, organization_name,
                        role, roles_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        user_dict["email"],
                        password_hash,
                        user_dict["name"],
                        user_dict["name"],
                        user_dict["organisation_name"],
                        user_dict["organisation_name"],
                        user_dict["role"],
                        f'["{user_dict["role"]}"]',
                        now_iso,
                        now_iso,
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"User saved to fallback buffer: {exc}")

        _FALLBACK_USERS[user_id] = user_dict
        _FALLBACK_USERS[user_dict["email"]] = user_dict

        return UserResponse(
            user_id=user_id,
            email=user_dict["email"],
            name=user_dict["name"],
            organisation_name=user_dict["organisation_name"],
            role=UserRole(user_dict["role"]),
            created_at=datetime.fromisoformat(now_iso),
        )

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Fetch raw user record including password_hash by normalized email."""
        clean_email = email.strip().lower()
        try:
            with sqlite_connection(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM users WHERE email = ?",
                    (clean_email,),
                ).fetchone()

            if row:
                res = dict(row)
                res["name"] = res.get("name") or res.get("full_name") or ""
                res["organisation_name"] = res.get("organisation_name") or res.get("organization_name") or ""
                res["role"] = res.get("role") or "SEEKER"
                return res
            return None
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying user by email: {exc}")
            return _FALLBACK_USERS.get(clean_email)

    def get_user_by_id(self, user_id: str) -> Optional[UserResponse]:
        """Fetch sanitized user response by user_id."""
        try:
            with sqlite_connection(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM users WHERE user_id = ?",
                    (user_id,),
                ).fetchone()

            if row:
                row_dict = dict(row)
                name = row_dict.get("name") or row_dict.get("full_name") or ""
                org = row_dict.get("organisation_name") or row_dict.get("organization_name") or ""
                role_val = row_dict.get("role") or "SEEKER"
                created_at_dt = (
                    datetime.fromisoformat(row_dict["created_at"])
                    if row_dict.get("created_at")
                    else datetime.now(timezone.utc)
                )
                return UserResponse(
                    user_id=row_dict["user_id"],
                    email=row_dict["email"],
                    name=name,
                    organisation_name=org,
                    role=UserRole(role_val),
                    created_at=created_at_dt,
                )
            return None
        except (sqlite3.Error, OSError) as exc:
            logger.warning(f"Error querying user by ID: {exc}")
            fb = _FALLBACK_USERS.get(user_id)
            if fb:
                return UserResponse(
                    user_id=fb["user_id"],
                    email=fb["email"],
                    name=fb["name"],
                    organisation_name=fb["organisation_name"],
                    role=UserRole(fb["role"]),
                    created_at=datetime.fromisoformat(fb["created_at"]),
                )
            return None
