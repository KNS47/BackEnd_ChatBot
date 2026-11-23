"""Cloudflare Workers AI transport for the Render-hosted application."""

import json
import logging
import math
import re

import httpx

from usage_counter import add_generation_usage

logger = logging.getLogger(__name__)
DEFAULT_GENERATION_MODEL = "@cf/google/gemma-4-26b-a4b-it"
EMBEDDING_MODEL = "@cf/baai/bge-m3"
EMBEDDING_DIMENSIONS = 1024


class CloudflareUnavailable(RuntimeError):
    pass


class CloudflareQuotaExceeded(CloudflareUnavailable):
    pass


class _SchemaRejected(CloudflareUnavailable):
    pass


def _json_schema(schema: dict) -> dict:
    converted = dict(schema)
    if isinstance(schema.get("type"), str):
        converted["type"] = schema["type"].lower()
    if "properties" in schema:
        converted["properties"] = {name: _json_schema(item) for name, item in schema["properties"].items()}
    if "items" in schema:
        converted["items"] = _json_schema(schema["items"])
    return converted


def _error_code(payload: dict):
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("code")
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return errors[0].get("code")
    return None


class CloudflareTransport:
    def __init__(self, account_id: str, api_token: str, model: str = DEFAULT_GENERATION_MODEL):
        self._base = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai"
            if re.fullmatch(r"[a-fA-F0-9]{32}", account_id)
            else None
        )
        self._token = api_token
        self._model = model

    async def _post(
        self, client: httpx.AsyncClient, path: str, body: dict, *, with_schema: bool = False,
    ) -> dict:
        if not self._base or not self._token:
            raise CloudflareUnavailable("Workers AI account configuration is missing")
        try:
            response = await client.post(
                self._base + path,
                headers={"Authorization": f"Bearer {self._token}"},
                json=body,
                timeout=httpx.Timeout(11, connect=3),
            )
        except httpx.HTTPError as exc:
            logger.warning("Workers AI request failed: %s", type(exc).__name__)
            raise CloudflareUnavailable("Workers AI request failed") from None

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        code = _error_code(payload)
        if str(code) == "3036":
            raise CloudflareQuotaExceeded("Workers AI daily quota reached")
        if response.status_code == 429:
            raise CloudflareUnavailable("Workers AI capacity or rate limit reached")
        if with_schema and response.status_code in {400, 422} and str(code) not in {"3003", "5004", "5007"}:
            raise _SchemaRejected("Workers AI JSON schema was rejected")
        if not response.is_success or not payload or payload.get("success") is False or "error" in payload:
            logger.warning("Workers AI returned HTTP %s", response.status_code)
            raise CloudflareUnavailable("Workers AI did not return a usable response")
        return payload

    async def embed(self, client: httpx.AsyncClient, text: str) -> list[float]:
        payload = await self._post(client, f"/run/{EMBEDDING_MODEL}", {"text": [text]})
        result = payload.get("result")
        rows = result.get("data") if isinstance(result, dict) else None
        values = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
        if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSIONS or not all(
            type(value) in {int, float} and math.isfinite(value) for value in values
        ):
            raise CloudflareUnavailable("Workers AI returned an invalid BGE-M3 embedding")
        return values

    async def generate(
        self, client: httpx.AsyncClient, prompt: str, instructions: str | None,
        response_schema: dict | None, token_limit: int,
    ) -> str:
        schema = _json_schema(response_schema) if response_schema is not None else None
        if schema is not None:
            schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            instructions = (
                f"{instructions or ''}\nReturn one JSON object only, without Markdown. "
                f"Follow this JSON Schema: {schema_text}"
            ).strip()
        messages = [{"role": "system", "content": instructions}] if instructions else []
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self._model,
            "messages": messages,
            "max_completion_tokens": token_limit,
            "store": False,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "municipal_answer", "schema": schema},
            }
        try:
            payload = await self._post(client, "/v1/chat/completions", body, with_schema=schema is not None)
        except _SchemaRejected:
            # Not every model implements the optional response_format parameter.
            del body["response_format"]
            payload = await self._post(client, "/v1/chat/completions", body)

        usage = payload.get("usage")
        if isinstance(usage, dict):
            add_generation_usage({"usageMetadata": {"totalTokenCount": usage.get("total_tokens")}})
        choices = payload.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get("message")
        answer = message.get("content") if isinstance(message, dict) else None
        if not isinstance(answer, str) or not answer.strip() or choice.get("finish_reason") not in (None, "stop"):
            raise CloudflareUnavailable("Workers AI returned an incomplete answer")
        answer = answer.strip()
        if schema is not None:
            fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", answer, flags=re.IGNORECASE | re.DOTALL)
            if fenced:
                answer = fenced.group(1)
            try:
                parsed = json.loads(answer)
            except ValueError:
                raise CloudflareUnavailable("Workers AI returned invalid JSON") from None
            if not isinstance(parsed, dict):
                raise CloudflareUnavailable("Workers AI returned a non-object structured answer")
        return answer
