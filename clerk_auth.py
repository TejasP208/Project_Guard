"""Narrow Clerk session verification used by profile-linking endpoints."""

import os
from urllib.parse import urlsplit

from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from fastapi import HTTPException, Request


def _authorized_parties() -> list[str]:
    configured = os.getenv("CLERK_AUTHORIZED_PARTIES", "")
    parties = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    if parties:
        if _is_production_environment():
            for party in parties:
                parsed = urlsplit(party)
                if (parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment
                        or "*" in party or parsed.username or parsed.password):
                    raise HTTPException(
                        status_code=503,
                        detail="CLERK_AUTHORIZED_PARTIES must contain exact HTTPS frontend origins.",
                    )
        return parties

    if _is_production_environment():
        raise HTTPException(
            status_code=503,
            detail="CLERK_AUTHORIZED_PARTIES must be configured for production.",
        )

    # Local static server origins for development only.
    return ["http://127.0.0.1:5500", "http://localhost:5500"]


def _is_production_environment() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() == "production" or os.getenv("RENDER", "").lower() == "true"


def _origin_identity(value: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(value)
    port = parsed.port
    if (parsed.scheme.lower(), port) in {("https", 443), ("http", 80)}:
        port = None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def validate_production_clerk_config() -> None:
    """Fail startup when production would use development or incomplete keys."""
    if not _is_production_environment():
        return
    publishable_key = os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "").strip()
    secret_key = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not publishable_key.startswith("pk_live_"):
        raise RuntimeError("Production requires a Clerk pk_live_ publishable key.")
    if not secret_key.startswith("sk_live_"):
        raise RuntimeError("Production requires a Clerk sk_live_ secret key.")
    rate_limit_key = os.getenv("RATE_LIMIT_HASH_KEY", "").strip()
    if len(rate_limit_key) < 32:
        raise RuntimeError("Production requires a separate RATE_LIMIT_HASH_KEY of at least 32 characters.")
    if rate_limit_key == secret_key or rate_limit_key == publishable_key:
        raise RuntimeError("RATE_LIMIT_HASH_KEY must be independent from Clerk keys.")
    missing = [name for name in (
        "GROQ_API_KEY",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "ENROLLMENT_ADMIN_CLERK_USER_IDS",
    ) if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("Production is missing required backend environment values: " + ", ".join(missing))
    # Validate and require exact production HTTPS origins before serving traffic.
    authorized = _authorized_parties()
    cors = [origin.strip().rstrip("/") for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
    if not cors:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must list the deployed HTTPS frontend origin(s).")
    if {_origin_identity(origin) for origin in authorized} != {_origin_identity(origin) for origin in cors}:
        raise RuntimeError("CORS_ALLOWED_ORIGINS and CLERK_AUTHORIZED_PARTIES must contain the same frontend origins.")


def require_clerk_user_id(request: Request) -> str:
    """Return the verified Clerk subject from a session-token bearer request."""
    secret_key = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not secret_key:
        raise HTTPException(status_code=503, detail="Clerk authentication is not configured.")

    try:
        state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                secret_key=secret_key,
                jwt_key=os.getenv("CLERK_JWT_KEY") or None,
                authorized_parties=_authorized_parties(),
                accepts_token=["session_token"],
            ),
        )
    except Exception as error:  # noqa: BLE001 - SDK/network failures must fail closed
        raise HTTPException(
            status_code=503,
            detail="Clerk could not verify the session right now.",
        ) from error

    if not state.is_signed_in:
        reason = state.reason.name if state.reason else "unauthorized"
        raise HTTPException(
            status_code=401,
            detail=reason,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = state.payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Clerk session has no user ID.")
    return user_id
