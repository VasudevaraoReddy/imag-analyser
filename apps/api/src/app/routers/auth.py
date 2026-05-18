from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.auth_service import issue_token, verify

router = APIRouter()


class LoginRequest(BaseModel):
    employee_id: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    employee_id: str
    name: str
    role: str
    email: str
    token: str


@router.post("/auth/login", response_model=LoginResponse)
def post_login(req: LoginRequest) -> LoginResponse:
    user = verify(req.employee_id, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid employee ID or password")
    return LoginResponse(**user, token=issue_token())
