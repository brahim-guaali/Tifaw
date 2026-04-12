from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from tifaw.chat.agent import run_agent

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
    """Stream chat with status updates so the user knows what's happening."""
    from tifaw.main import app, db, llm

    queue = getattr(app.state, "index_queue", None)

    async def generate():
        if queue and queue._queue.qsize() > 0:
            queue.pause()
            yield _sse("status", "Pausing indexing...")

        try:
            yield _sse("status", "Thinking...")
            response = await run_agent(req.message, db, llm)
            yield _sse("done", response)
        except Exception as e:
            yield _sse("error", str(e))
        finally:
            if queue:
                queue.resume()

    return StreamingResponse(generate(), media_type="text/event-stream")


def _sse(event: str, data: str) -> str:
    # Escape newlines for SSE format
    safe = data.replace("\n", "\\n")
    return f"event: {event}\ndata: {json.dumps(safe)}\n\n"
