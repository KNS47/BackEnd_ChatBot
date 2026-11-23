import json
import os
import unittest
from unittest.mock import MagicMock, patch

import httpx
from google.auth.exceptions import DefaultCredentialsError

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-placeholder")
os.environ.setdefault("SESSION_SECRET", "test-placeholder")

import ai
from vertex_ai import VertexTransport


class VertexTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_uses_adc_and_publisher_path_with_model_fallback(self):
        credentials = MagicMock()
        credentials.before_request.side_effect = (
            lambda auth_request, method, url, headers: headers.update(authorization="Bearer fixture")
        )
        requests = []

        def handle(request):
            requests.append(request)
            if str(request.url).endswith("gemini-3.5-flash-lite:generateContent"):
                return httpx.Response(429)
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "ready"}]}}]},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with (
                patch.object(ai, "_vertex", VertexTransport("staging-project", "global")),
                patch.object(ai, "_client", client),
                patch.object(ai, "GENERATION_MODELS", ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")),
                patch("vertex_ai.google.auth.default", return_value=(credentials, None)) as adc,
            ):
                result = await ai.generate_answer("test", response_schema={"type": "OBJECT"})
        self.assertEqual(result, "ready")
        adc.assert_called_once()
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request.url.host, "aiplatform.googleapis.com")
            self.assertIn("/v1/projects/staging-project/locations/global/publishers/google/models/", request.url.path)
            self.assertEqual(request.headers["Authorization"], "Bearer fixture")
            self.assertEqual(json.loads(request.content)["generationConfig"]["responseMimeType"], "application/json")

    async def test_embedding_uses_predict_and_enforces_index_dimensions(self):
        provider_response = {"predictions": [{"embeddings": {"values": [0.1] * 3072}}]}

        def handle(request):
            self.assertEqual(request.url.host, "us-central1-aiplatform.googleapis.com")
            self.assertTrue(request.url.path.endswith("/gemini-embedding-001:predict"))
            self.assertEqual(json.loads(request.content), {
                "instances": [{"content": "municipal test"}],
                "parameters": {"outputDimensionality": 3072, "autoTruncate": False},
            })
            return httpx.Response(200, json=provider_response)

        transport = VertexTransport("staging-project", "us-central1")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with (
                patch.object(ai, "_vertex", transport),
                patch.object(ai, "_client", client),
                patch.object(transport, "_authorize", return_value={}),
            ):
                self.assertEqual(len(await ai.embed_text("municipal test")), 3072)
                provider_response["predictions"][0]["embeddings"]["values"].pop()
                with self.assertRaisesRegex(ai.AIUnavailable, "invalid embedding"):
                    await ai.embed_text("municipal test")

    async def test_missing_adc_fails_without_network_or_credential_details(self):
        def unexpected_request(request):
            self.fail("Request attempted without ADC")

        async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected_request)) as client:
            with (
                patch.object(ai, "_vertex", VertexTransport("staging-project", "global")),
                patch.object(ai, "_client", client),
                patch("vertex_ai.google.auth.default", side_effect=DefaultCredentialsError("private context")),
                self.assertLogs("vertex_ai", level="WARNING") as logs,
            ):
                with self.assertRaisesRegex(ai.AIUnavailable, "^Vertex credentials unavailable$"):
                    await ai.generate_answer("test")
        self.assertNotIn("private context", str(logs.output))
