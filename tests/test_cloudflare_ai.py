import json
import os
import unittest
from unittest.mock import patch

import httpx

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-placeholder")
os.environ.setdefault("SESSION_SECRET", "test-placeholder")

import ai
from cloudflare_ai import CloudflareTransport, DEFAULT_GENERATION_MODEL, EMBEDDING_DIMENSIONS
from usage_counter import generation_usage

ACCOUNT_ID = "1234567890abcdef1234567890abcdef"
SCHEMA = {
    "type": "OBJECT",
    "properties": {"answer": {"type": "STRING"}, "sources": {"type": "ARRAY", "items": {"type": "INTEGER"}}},
    "required": ["answer", "sources"],
}


class CloudflareTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_maps_schema_and_reports_provider_usage(self):
        def handle(request):
            self.assertEqual(request.url.path, f"/client/v4/accounts/{ACCOUNT_ID}/ai/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer fixture")
            body = json.loads(request.content)
            self.assertEqual(body["model"], DEFAULT_GENERATION_MODEL)
            self.assertEqual(body["max_completion_tokens"], 100)
            self.assertFalse(body["store"])
            schema = body["response_format"]["json_schema"]["schema"]
            self.assertEqual(schema["type"], "object")
            self.assertEqual(schema["properties"]["sources"]["items"]["type"], "integer")
            self.assertEqual(body["messages"][-1], {"role": "user", "content": "เวลาทำการ"})
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"answer":"08:45","sources":[1]}'}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 121},
            })

        usage = [0]
        reset = generation_usage.set(usage)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                with (
                    patch.object(ai, "_cloudflare", CloudflareTransport(ACCOUNT_ID, "fixture")),
                    patch.object(ai, "_client", client),
                ):
                    answer = await ai.generate_answer("เวลาทำการ", response_schema=SCHEMA, token_limit=100)
        finally:
            generation_usage.reset(reset)
        self.assertEqual(json.loads(answer), {"answer": "08:45", "sources": [1]})
        self.assertEqual(usage, [121])

    async def test_embeds_via_bge_m3_and_rejects_invalid_dimensions(self):
        response_vector = [0.1] * EMBEDDING_DIMENSIONS

        def handle(request):
            self.assertEqual(request.url.path, f"/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/baai/bge-m3")
            self.assertEqual(json.loads(request.content), {"text": ["ตัวอย่าง"]})
            return httpx.Response(200, json={"result": {"data": [response_vector]}, "success": True})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with (
                patch.object(ai, "_cloudflare", CloudflareTransport(ACCOUNT_ID, "fixture")),
                patch.object(ai, "_client", client),
            ):
                self.assertEqual(len(await ai.embed_text("ตัวอย่าง")), 1024)
                response_vector.pop()
                with self.assertRaisesRegex(ai.AIUnavailable, "invalid BGE-M3 embedding"):
                    await ai.embed_text("ตัวอย่าง")

    async def test_schema_rejection_falls_back_to_constrained_prompt(self):
        bodies = []

        def handle(request):
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                return httpx.Response(400, json={"error": {"message": "Unsupported response_format"}})
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"","sources":[]}'}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            transport = CloudflareTransport(ACCOUNT_ID, "fixture")
            result = await transport.generate(client, "question", None, SCHEMA, 100)
        self.assertEqual(json.loads(result)["sources"], [])
        self.assertEqual(len(bodies), 2)
        self.assertNotIn("response_format", bodies[1])
        self.assertIn("Return one JSON object only", bodies[1]["messages"][0]["content"])

    async def test_daily_quota_is_reported_without_retry_or_fallback(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(429, json={"errors": [{"code": 3036}], "success": False})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with (
                patch.object(ai, "_cloudflare", CloudflareTransport(ACCOUNT_ID, "fixture")),
                patch.object(ai, "_client", client),
            ):
                with self.assertRaisesRegex(ai.AIQuotaExceeded, "daily quota"):
                    await ai.generate_answer("question", response_schema=SCHEMA)
        self.assertEqual(len(requests), 1)

    async def test_missing_credentials_stops_before_requests(self):
        def handle(request):
            self.fail("Sent a request without valid configuration")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with self.assertRaisesRegex(RuntimeError, "configuration is missing"):
                await CloudflareTransport("", "").embed(client, "test")
