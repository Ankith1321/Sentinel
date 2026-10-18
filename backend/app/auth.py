import hmac
import os

from fastapi import Header, HTTPException, status

from backend.app import store

API_KEY_HEADER = "X-API-Key"


def auth_disabled() -> bool:
    return os.getenv("SENTINEL_AUTH", "on").lower() == "off"


def is_admin_key(candidate: str) -> bool:
    admin_key = os.getenv("SENTINEL_API_KEY", "")
    return bool(admin_key) and hmac.compare_digest(candidate.encode("utf-8"), admin_key.encode("utf-8"))


def reject() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid API key",
        headers={"WWW-Authenticate": API_KEY_HEADER},
    )


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if auth_disabled():
        return

    if not x_api_key or not (is_admin_key(x_api_key) or store.api_key_is_active(x_api_key)):
        raise reject()


def require_admin_key(x_api_key: str | None = Header(default=None)) -> None:
    if auth_disabled():
        return

    if not x_api_key or not is_admin_key(x_api_key):
        raise reject()
