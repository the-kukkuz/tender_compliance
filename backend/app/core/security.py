"""Authentication, cryptographic password hashing, and signed JWT token utilities."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """Hash a plain text password using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = secrets.token_bytes(16)
    iterations = 100_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a stored PBKDF2 hash."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_dk = parts[3]

        computed_dk = hashlib.pbkdf2_hmac(
            "sha256", plain_password.encode("utf-8"), salt, iterations
        ).hex()
        return hmac.compare_digest(computed_dk, expected_dk)
    except (ValueError, IndexError):
        return False


def _b64url_encode(data: bytes) -> str:
    """Encode bytes into base64url string without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data_str: str) -> bytes:
    """Decode base64url string with flexible padding."""
    padding = 4 - (len(data_str) % 4)
    if padding and padding != 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str.encode("ascii"))


def create_access_token(
    data: Dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """Generate a signed HMAC-SHA256 JWT access token."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(hours=settings.token_expiry_hours)

    payload = data.copy()
    payload.update({
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    })

    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    b64_header = _b64url_encode(header_json)
    b64_payload = _b64url_encode(payload_json)

    signing_input = f"{b64_header}.{b64_payload}".encode("ascii")
    secret_bytes = settings.secret_key.encode("utf-8")
    sig = hmac.new(secret_bytes, signing_input, hashlib.sha256).digest()
    b64_sig = _b64url_encode(sig)

    return f"{b64_header}.{b64_payload}.{b64_sig}"


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify signature and expiration of an access token, returning the payload if valid."""
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None

        b64_header, b64_payload, b64_sig = parts
        signing_input = f"{b64_header}.{b64_payload}".encode("ascii")
        settings = get_settings()
        secret_bytes = settings.secret_key.encode("utf-8")

        expected_sig = hmac.new(secret_bytes, signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(b64_sig)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload_bytes = _b64url_decode(b64_payload)
        payload = json.loads(payload_bytes.decode("utf-8"))

        now_ts = int(datetime.now(timezone.utc).timestamp())
        if "exp" in payload and payload["exp"] < now_ts:
            return None

        return payload
    except Exception:
        return None
