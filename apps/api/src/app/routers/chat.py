from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.chatbot import answer

router = APIRouter()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    analysis_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    analysis_id: str | None = None
    used_mock: bool | None = None


@router.post("/chat", response_model=ChatResponse)
async def post_chat(req: ChatRequest) -> ChatResponse:
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    msgs = [m.model_dump() for m in req.messages]
    try:
        reply = await answer(msgs, req.analysis_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"chat upstream error: {exc}") from exc
    return ChatResponse(reply=reply, analysis_id=req.analysis_id)
