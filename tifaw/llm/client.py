from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

MAX_IMAGE_DIMENSION = 1024


def _resize_image_bytes(image_bytes: bytes) -> bytes:
    import io

    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    if max(w, h) <= MAX_IMAGE_DIMENSION:
        return image_bytes
    scale = MAX_IMAGE_DIMENSION / max(w, h)
    new_size = (int(w * scale), int(h * scale))
    img = img.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    fmt = img.format or "PNG"
    img.save(buf, format=fmt)
    return buf.getvalue()


def _encode_image(path: Path) -> str:
    image_bytes = path.read_bytes()
    image_bytes = _resize_image_bytes(image_bytes)
    return base64.b64encode(image_bytes).decode()


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags")
            return resp.status_code == 200
        except httpx.ConnectError:
            return False

    async def model_available(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags")
            if resp.status_code != 200:
                return False
            models = resp.json().get("models", [])
            return any(m.get("name", "").startswith(self.model) for m in models)
        except httpx.ConnectError:
            return False

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        images: list[str] | None = None,
        temperature: float = 0.3,
    ) -> str:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})

        user_msg: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user_msg["images"] = images
        messages.append(user_msg)

        resp = await self._client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    async def generate_json(
        self,
        prompt: str,
        system: str | None = None,
        images: list[str] | None = None,
    ) -> dict:
        response = await self.generate(prompt, system=system, images=images, temperature=0.2)

        # Extract JSON from response (handle markdown code blocks)
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            json_lines = []
            inside = False
            for line in lines:
                if line.strip().startswith("```") and not inside:
                    inside = True
                    continue
                if line.strip() == "```" and inside:
                    break
                if inside:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
            logger.warning("Failed to parse JSON from LLM response: %s", text[:200])
            return {"description": text[:200], "tags": [], "category": "Other"}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        temperature: float = 0.4,
    ) -> dict:
        """Non-streaming chat that returns the full assistant message dict.

        The returned dict has at minimum a ``role`` and ``content`` key.
        When the model invokes tools it also contains ``tool_calls``.
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            body["tools"] = tools

        resp = await self._client.post(
            f"{self.base_url}/api/chat",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()["message"]

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        async with self._client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=body,
            timeout=httpx.Timeout(300.0, connect=10.0),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    def encode_image_file(self, path: Path) -> str:
        return _encode_image(path)
