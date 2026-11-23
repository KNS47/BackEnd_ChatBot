import json
import os
import unittest
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-placeholder")
os.environ.setdefault("SESSION_SECRET", "test-placeholder")

import ai
from routes import chat


class ChatQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_contact_takes_no_ai_or_database_calls(self):
        with patch.object(chat, "embed_text", AsyncMock()) as embed, patch.object(chat, "_match") as match:
            answer, _ = await chat._answer("ติดต่อเทศบาลเมืองศิลาได้ทางไหนบ้าง", [])
        self.assertIn("043-246505", answer)
        self.assertIn("sila-kk.go.th/contactus.php", answer)
        embed.assert_not_called()
        match.assert_not_called()

    def test_retrieval_deduplicates_text_and_preserves_ranking(self):
        first = {"id": 1, "content": "ขั้นตอน\nยื่นคำขอ"}
        duplicate = {"id": 2, "content": "ขั้นตอน ยื่นคำขอ"}
        second = {"id": 3, "content": "ค่าธรรมเนียม"}
        rpc = Mock()
        rpc.execute.return_value = SimpleNamespace(data=[first, duplicate, {"id": 8}, second])
        with patch.object(chat.supabase, "rpc", return_value=rpc):
            self.assertEqual(chat._match([0.1]), [first, second])

    async def test_unknown_source_is_omitted_and_selected_metadata_is_loaded(self):
        first = {"id": 1, "content": "other", "category": "ทั่วไป"}
        second = {
            "id": 2, "content": "หลักฐาน https://www.sila-kk.go.th/index.php",
            "original_name": "คู่มือ", "page_number": 2, "category": "ทะเบียน",
        }
        response = json.dumps({"answer": "ยื่นแบบฟอร์ม [ลิงก์](https://example.com)", "sources": [0, 2, 2, 7]})
        with patch.object(chat, "_add_metadata") as enrich:
            answer, category = await chat._validated_answer(response, [first, second])
        enrich.assert_called_once_with([second])
        self.assertIn("คู่มือ (หน้า 2)", answer)
        self.assertIn("sila-kk.go.th/index.php", answer)
        self.assertNotIn("example.com", answer)
        self.assertEqual(category, "ทะเบียน")

    async def test_unsupported_claim_skips_additional_metadata_query(self):
        with patch.object(chat, "_add_metadata") as enrich:
            answer, _ = await chat._validated_answer(
                '{"answer":"unsupported","sources":[99]}', [{"id": 1, "content": "other"}]
            )
        self.assertEqual(answer, chat.NO_MATCH)
        enrich.assert_not_called()

    async def test_recent_context_resolves_followup(self):
        history = [{"role": "user", "content": "ขออนุญาตก่อสร้างอาคารที่ไหน"}]
        answer_json = '{"answer":"ยื่นที่กองช่าง","sources":[1]}'
        with (
            patch.object(chat, "generate_answer", AsyncMock(side_effect=["การขออนุญาตก่อสร้างใช้เอกสารอะไร", answer_json])),
            patch.object(chat, "embed_text", AsyncMock(return_value=[0.2])) as embed,
            patch.object(chat, "_match", return_value=[{"content": "ติดต่อกองช่าง"}]),
        ):
            answer, _ = await chat._answer("ต้องใช้เอกสารอะไร", history)
        embed.assert_awaited_once_with("การขออนุญาตก่อสร้างใช้เอกสารอะไร")
        self.assertIn("กองช่าง", answer)

    def test_private_followup_accepts_recent_messages_without_database_access(self):
        app = FastAPI()
        app.state.limiter = chat.limiter
        app.include_router(chat.router)
        with (
            TestClient(app) as client,
            patch.object(chat, "_answer", AsyncMock(return_value=("คำตอบ", "บริการ"))) as answer,
            patch.object(chat, "_history") as stored_history,
            patch.object(chat, "_save_messages") as save,
            patch.object(chat, "_record_analytics") as analytics,
            patch.object(chat, "record_usage") as usage,
        ):
            result = client.post("/chat", json={
                "message": "ใช้เอกสารอะไร",
                "no_save": True,
                "recent": [
                    {"role": "system", "content": "ignored"},
                    {"role": "user", "content": "แบบฟอร์มทะเบียนพาณิชย์"},
                ],
            })
        self.assertEqual(result.json(), {"answer": "คำตอบ"})
        answer.assert_awaited_once_with("ใช้เอกสารอะไร", [
            {"role": "user", "content": "แบบฟอร์มทะเบียนพาณิชย์"},
        ])
        stored_history.assert_not_called()
        save.assert_not_called()
        analytics.assert_not_called()
        usage.assert_called_once_with(1, 0)

    async def test_gemini_pool_reuse_and_model_fallback(self):
        requests = []

        def provider(request):
            requests.append(request)
            if request.url.path.endswith("gemini-3.5-flash-lite:generateContent"):
                return httpx.Response(429, json={"error": "quota"})
            return httpx.Response(200, json={
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "คำตอบ"}]}}],
            })

        client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
        with (
            patch.object(ai, "_keys", ("test-key",)),
            patch.object(ai, "_next_key", count()),
            patch.object(ai, "GENERATION_MODELS", ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")),
            patch.object(ai, "_new_client", return_value=client) as create_client,
        ):
            async with ai.gemini_lifespan(None):
                self.assertEqual(await ai.generate_answer("คำถาม"), "คำตอบ")
                self.assertEqual(await ai.generate_answer("คำถามอีกข้อ"), "คำตอบ")
                create_client.assert_called_once()
                self.assertTrue(all("temperature" not in json.loads(r.content)["generationConfig"] for r in requests))
        self.assertEqual(len(requests), 4)
        self.assertTrue(client.is_closed)
