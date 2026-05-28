from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..services.auth_service import (
    extract_bearer,
    issue_token,
    resolve_token,
    verify,
)

router = APIRouter()


class LoginRequest(BaseModel):
    employee_id: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    employee_id: str
    name: str
    role: str
    email: str
    is_admin: bool = False
    token: str


@router.post("/auth/login", response_model=LoginResponse)
def post_login(req: LoginRequest) -> LoginResponse:
    user = verify(req.employee_id, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid employee ID or password")
    token = issue_token(user)
    return LoginResponse(**user, token=token)


# ---------------------------------------------------------------------------
# Dependencies usable by any other router
# ---------------------------------------------------------------------------

def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Require a valid bearer token; return the public user record.

    On failure raises 401 with a structured body so the frontend can
    distinguish ``session_expired`` (force-logout + banner) from
    ``not_authenticated`` (regular 401, no banner).
    """
    token = extract_bearer(authorization)
    user, status = resolve_token(token or "")
    if user is not None:
        return user
    if status == "expired":
        raise HTTPException(
            status_code=401,
            detail={
                "error": "session_expired",
                "message": "Your session has expired. Please sign in again.",
            },
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", '
                                          'error_description="The access token expired"'},
        )
    raise HTTPException(
        status_code=401,
        detail={
            "error": "not_authenticated",
            "message": "Not authenticated.",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_admin(user: dict = Depends(current_user)) -> dict:
    """Same as current_user, but also requires is_admin=True."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
