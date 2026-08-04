import structlog
from fastapi import APIRouter, HTTPException

from app.auth.schemas import LoginRequest, LoginResponse
from app.auth.security import InvalidCredentials, create_access_token, verify_credentials

router = APIRouter(prefix="/auth", tags=["auth"])
logger = structlog.get_logger("auth")


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    try:
        verify_credentials(body.username, body.password)
    except InvalidCredentials as exc:
        # The specific reason is logged (Phase 10: no silent 401s) but
        # never returned to the client — the response stays generic so
        # a caller can't use it to enumerate valid usernames.
        logger.warning("auth_login_failed", username=body.username, reason=str(exc))
        raise HTTPException(status_code=401, detail="invalid username or password") from exc

    logger.info("auth_login_succeeded", username=body.username)
    return LoginResponse(access_token=create_access_token(body.username))
