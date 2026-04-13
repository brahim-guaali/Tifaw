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
    from tifaw.main import app, db, llm

    # Pause indexing so Ollama is free for chat
    queue = getattr(app.state, "index_queue", None)
    if queue:
        queue.pause()

    try:
        response = await run_agent(req.message, db, llm)
        return {"response": response}
    except Exception as e:
        return {"response": f"Error: {e}"}
    finally:
        # Resume indexing
        if queue:
            queue.resume()


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream chat response token by token using newline-delimited JSON."""
    from tifaw.main import app, db, llm

    queue = getattr(app.state, "index_queue", None)

    async def generate():
        if queue:
            queue.pause()

        try:
            async for chunk in run_agent_stream(req.message, db, llm):
                yield chunk
        except Exception as e:
            yield json.dumps({"type": "error", "text": str(e)}) + "\n"
        finally:
            if queue:
                queue.resume()

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
