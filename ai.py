import asyncio
import logging
import math
import os
from contextlib import asynccontextmanager
from itertools import count

import httpx

from config import API_KEYS

logger = logging.getLogger(__name__)
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 3072
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
if AI_PROVIDER not in {"gemini", "vertex"}:
    raise ValueError("Set AI_PROVIDER to gemini or vertex")
GENERATION_MODELS = tuple(dict.fromkeys(
    model.strip()
    for model in os.getenv(
        "GEMINI_GENERATION_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    ).split(",")
    if model.strip()
))
_keys = tuple(dict.fromkeys(key.strip() for key in API_KEYS if key.strip()))
_next_key = count()
_client: httpx.AsyncClient | None = None
if AI_PROVIDER == "vertex":
    from vertex_ai import VertexTransport

    _vertex = VertexTransport(
        os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
        os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip(),
    )
else:
    _vertex = None


class AIUnavailable(RuntimeError):
    pass


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(7.0, connect=3.0))


@asynccontextmanager
async def gemini_lifespan(app):
    global _client
    async with _new_client() as client:
        _client = client
        try:
            yield
        finally:
            _client = None


async def _request(action: str, models: tuple[str, ...], body: dict) -> dict:
    if _vertex is not None:
        from vertex_ai import VertexUnavailable

        try:
            if _client is not None:
                return await _vertex.request(_client, action, models, body)
            async with _new_client() as client:
                return await _vertex.request(client, action, models, body)
        except VertexUnavailable as exc:
            raise AIUnavailable(str(exc)) from None
    if not _keys or not models:
        raise AIUnavailable("Gemini credentials or models are missing")
    if _client is not None:
        return await _try_request(_client, action, models, body)
    async with _new_client() as client:
        return await _try_request(client, action, models, body)


async def _try_request(
    client: httpx.AsyncClient, action: str, models: tuple[str, ...], body: dict,
) -> dict:
    start = next(_next_key) % len(_keys)
    ordered_keys = _keys[start:] + _keys[:start]
    attempts = 0
    for key in ordered_keys:
        for model in models:
            if attempts >= 4:
                raise AIUnavailable("Gemini exhausted its fallback attempts")
            attempts += 1
            try:
                response = await asyncio.wait_for(
                    client.post(
                        f"{BASE_URL}/{model}:{action}",
                        headers={"x-goog-api-key": key},
                        json=body,
                    ),
                    timeout=8,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
                logger.warning("Gemini %s/%s returned an unexpected payload", model, action)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                logger.warning("Gemini %s/%s returned HTTP %s", model, action, status)
                if status == 401:
                    break
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
                logger.warning("Gemini %s/%s failed: %s", model, action, type(exc).__name__)
    raise AIUnavailable("Gemini did not return a usable response")


async def embed_text(text: str) -> list[float]:
    # Keep the existing corpus model, default task and default dimensions.
    if _vertex is not None:
        result = await _request("predict", (EMBEDDING_MODEL,), {
            "instances": [{"content": text}],
            "parameters": {"outputDimensionality": EMBEDDING_DIMENSIONS, "autoTruncate": False},
        })
        predictions = result.get("predictions")
        if not isinstance(predictions, list) or not predictions or not isinstance(predictions[0], dict):
            raise AIUnavailable("Vertex returned an invalid embedding")
        embedding = predictions[0].get("embeddings")
        values = embedding.get("values") if isinstance(embedding, dict) else None
        if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSIONS or not all(
            type(value) in {int, float} and math.isfinite(value) for value in values
        ):
            raise AIUnavailable("Vertex returned an invalid embedding")
        return values
    body = {"model": f"models/{EMBEDDING_MODEL}", "content": {"parts": [{"text": text}]}}
    result = await _request("embedContent", (EMBEDDING_MODEL,), body)
    values = result.get("embedding", {}).get("values")
    if not isinstance(values, list) or not values:
        raise AIUnavailable("Gemini returned an empty embedding")
    return values


async def generate_answer(
    prompt: str,
    *,
    instructions: str | None = None,
    response_schema: dict | None = None,
    token_limit: int = 1200,
) -> str:
    options = {"maxOutputTokens": token_limit}
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": options}
    if instructions:
        body["systemInstruction"] = {"parts": [{"text": instructions}]}
    if response_schema:
        options["responseMimeType"] = "application/json"
        options["responseSchema"] = response_schema
    result = await _request("generateContent", GENERATION_MODELS, body)
    candidates = result.get("candidates") or []
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        answer = "".join(
            part.get("text", "") for part in parts if not part.get("thought")
        ).strip()
        if answer and candidates[0].get("finishReason") in (None, "STOP"):
            return answer
    raise AIUnavailable("Gemini returned an incomplete answer")
