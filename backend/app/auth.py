import hmac
import os

from fastapi import Header, HTTPException, status

API_KEY_HEADER = "X-API-Key"


def auth_disabled() -> bool:
    return os.getenv("SENTINEL_AUTH", "on").lower() == "off"


def is_valid_key(candidate: str) -> bool:
    expected = os.getenv("SENTINEL_API_KEY", "")
    return bool(expected) and hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if auth_disabled():
        return

    if not x_api_key or not is_valid_key(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )
