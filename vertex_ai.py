"""REST transport for Google Cloud's managed Gemini models."""

import asyncio
import logging
import re
from threading import Lock

import google.auth
from google.auth import exceptions
from google.auth.transport.requests import Request
import httpx

logger = logging.getLogger(__name__)
SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


class VertexUnavailable(RuntimeError):
    pass


class _CredentialRequest(Request):
    def __call__(self, url, method="GET", body=None, headers=None, timeout=5, **kwargs):
        return super().__call__(url, method, body, headers, min(timeout, 5), **kwargs)


class VertexTransport:
    def __init__(self, project: str, location: str):
        if not re.fullmatch(r"[a-z0-9-]+", project):
            raise ValueError("Set GOOGLE_CLOUD_PROJECT to a Google Cloud project ID")
        if not re.fullmatch(r"[a-z0-9-]+", location):
            raise ValueError("Set GOOGLE_CLOUD_LOCATION to a supported model location")
        host = f"{location}-aiplatform.googleapis.com"
        if location == "global":
            host = "aiplatform.googleapis.com"
        elif location in {"us", "eu"}:
            host = f"aiplatform.{location}.rep.googleapis.com"
        self._base = f"https://{host}/v1/projects/{project}/locations/{location}/publishers/google/models"
        self._credentials = None
        self._credential_lock = Lock()

    def _authorize(self, url: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        with self._credential_lock:
            request = _CredentialRequest()
            try:
                if self._credentials is None:
                    self._credentials, _ = google.auth.default(scopes=SCOPES, request=request)
                self._credentials.before_request(request, "POST", url, headers)
            finally:
                request.session.close()
        return headers

    async def request(
        self, client: httpx.AsyncClient, action: str, models: tuple[str, ...], body: dict,
    ) -> dict:
        for model in models[:4]:
            url = f"{self._base}/{model}:{action}"
            try:
                headers = await asyncio.wait_for(asyncio.to_thread(self._authorize, url), timeout=6)
            except (exceptions.GoogleAuthError, asyncio.TimeoutError, OSError) as exc:
                logger.warning("Vertex authorization unavailable: %s", type(exc).__name__)
                raise VertexUnavailable("Vertex credentials unavailable") from None
            try:
                response = await asyncio.wait_for(client.post(url, headers=headers, json=body), timeout=8)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
                logger.warning("Vertex %s/%s returned an unexpected payload", model, action)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                logger.warning("Vertex %s/%s returned HTTP %s", model, action, status)
                if status in {401, 403}:
                    break
            except (httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
                logger.warning("Vertex %s/%s failed: %s", model, action, type(exc).__name__)
        raise VertexUnavailable("Vertex did not return a usable response")
