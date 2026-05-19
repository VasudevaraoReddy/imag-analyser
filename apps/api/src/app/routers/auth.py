from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ..services.auth_service import (
    extract_bearer,
    issue_token,
    user_for_token,
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
    """Require a valid bearer token; return the public user record."""
    token = extract_bearer(authorization)
    user = user_for_token(token or "")
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def current_admin(user: dict = Depends(current_user)) -> dict:
    """Same as current_user, but also requires is_admin=True."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
