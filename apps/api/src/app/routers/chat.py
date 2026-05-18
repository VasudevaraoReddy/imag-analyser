from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.chatbot import answer, stream_answer

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


@router.post("/chat/stream")
async def post_chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-Sent Events stream of response tokens.

    Wire format (one event per line pair, separated by ``\\n\\n``):
        data: {"delta": "Hello "}
        data: {"delta": "world."}
        data: [DONE]
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    msgs = [m.model_dump() for m in req.messages]

    async def event_gen():  # type: ignore[no-untyped-def]
        try:
            async for delta in stream_answer(msgs, req.analysis_id):
                payload = json.dumps({"delta": delta}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001
            err = json.dumps({"error": str(exc)})
            yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
        },
    )
