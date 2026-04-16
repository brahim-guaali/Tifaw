from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from tifaw.chat.agent import run_agent, run_agent_stream

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat(req: ChatRequest):
    """Run a chat request on the dedicated chat LLM client.

    Indexing workers use a separate LLM client pool, so chat is
    never blocked by indexing — both can run concurrently (subject
    to Ollama's configured parallelism).
    """
    from tifaw.main import chat_llm, db

    try:
        response = await run_agent(req.message, db, chat_llm)
        return {"response": response}
    except Exception as e:
        return {"response": f"Error: {e}"}


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream chat response token by token using newline-delimited JSON.

    Uses a dedicated chat LLM client; indexing is not paused.
    """
    from tifaw.main import chat_llm, db

    async def generate():
        try:
            async for chunk in run_agent_stream(
                req.message, db, chat_llm,
            ):
                yield chunk
        except Exception as e:
            yield json.dumps({"type": "error", "text": str(e)}) + "\n"

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
