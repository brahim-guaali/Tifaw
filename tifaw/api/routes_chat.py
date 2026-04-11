from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from tifaw.chat.agent import run_agent

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat(req: ChatRequest):
    from tifaw.main import db, llm

    try:
        response = await run_agent(req.message, db, llm)
        return {"response": response}
    except Exception as e:
        return {"response": f"Error: {e}"}
