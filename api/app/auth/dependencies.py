import jwt
import structlog
from fastapi import Header, HTTPException

from app.auth.security import decode_access_token

logger = structlog.get_logger("auth")


def require_auth(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency protecting the incidents router (see
    app/main.py). Returns the authenticated username on success; every
    failure path logs the specific reason (Phase 10: no silent 401s)
    before raising, while the HTTP response itself stays generic.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        logger.warning("auth_request_rejected", reason="missing bearer token")
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        return decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        logger.warning("auth_request_rejected", reason="token expired")
        raise HTTPException(status_code=401, detail="token expired") from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("auth_request_rejected", reason="invalid token")
        raise HTTPException(status_code=401, detail="invalid token") from exc
