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
    async def test_complaint_guide_faq_answers_without_ai(self):
        for question, expected in (
            ("ถ้าจะไปยื่นเรื่องร้องทุกข์ที่สำนักงาน ไปวันไหน เวลาใด", "08.30–16.30"),
            ("ร้องเรียนต้องจ่ายค่าธรรมเนียมไหม", "ไม่มีค่าธรรมเนียม"),
            ("ถ้ากรอกแบบฟอร์มร้องเรียน ต้องแนบอะไร", "สำเนาบัตรประจำตัวประชาชน"),
            ("เทศบาลรับประกันว่าจะจัดการเรื่องร้องเรียนเสร็จภายใน 15 วันไหม", "ไม่ได้กำหนดว่าเรื่องจะต้องแก้ไขเสร็จภายใน 15 วัน"),
        ):
            with self.subTest(question=question), patch.object(chat, "embed_text", AsyncMock()) as embed:
                answer, category = await chat._answer(question, [])
                self.assertIn(expected, answer)
                self.assertIn("19716284912632022.pdf#page=1", answer)
                self.assertEqual(category, "ร้องเรียน")
                embed.assert_not_awaited()

    async def test_complaint_followup_requires_explicit_latest_user_topic(self):
        complaint = {"role": "user", "content": "แจ้งเรื่องร้องเรียนได้ที่ไหน"}
        history = [
            complaint,
            {"role": "assistant", "content": "ไปที่สำนักงาน"},
            {"role": "user", "content": "แล้วเสียค่าธรรมเนียมไหม"},
        ]
        with patch.object(chat, "embed_text", AsyncMock()) as embed:
            answer, _ = await chat._answer("วันเสาร์เปิดไหม", history)
            self.assertIn("วันจันทร์ถึงวันศุกร์", answer)
            embed.assert_not_awaited()

        for other_history in (
            [],
            [{"role": "assistant", "content": "ร้องเรียนเทศบาล"}],
            [complaint, {"role": "user", "content": "ขออนุญาตก่อสร้างทำอย่างไร"}],
            [{"role": "user", "content": "ร้องเรียนการทุจริตทำอย่างไร"}],
        ):
            with (
                self.subTest(history=other_history),
                patch.object(chat, "generate_answer", AsyncMock(return_value="")),
                patch.object(chat, "embed_text", AsyncMock(return_value=[0.1])),
                patch.object(chat, "_match", return_value=[]),
            ):
                answer, _ = await chat._answer("แล้วเสียค่าธรรมเนียมไหม", other_history)
                self.assertEqual(answer, chat.NO_MATCH)

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

    async def test_numeric_value_must_appear_in_selected_evidence(self):
        matches = [{"content": "เปิด 08:45 น. https://www.sila-kk.go.th/news/500"}]
        answer, _ = await chat._validated_answer(
            '{"answer":"ค่าธรรมเนียม 500 บาท","sources":[1]}', matches,
        )
        self.assertEqual(answer, chat.NO_MATCH)

    async def test_numeric_thai_digits_and_list_markers_are_accepted(self):
        matches = [{"content": "ค่าธรรมเนียม ๑,๒๕๐ บาท", "category": "ค่าธรรมเนียม"}]
        answer, _ = await chat._validated_answer(
            json.dumps({"answer": "1. ชำระ 1250 บาท", "sources": [1]}), matches,
        )
        self.assertIn("1250 บาท", answer)

    async def test_numeric_value_with_incompatible_unit_is_rejected(self):
        for evidence, claim in (
            ("ยื่นเอกสารภายใน 5 วัน", "ค่าธรรมเนียม 5 บาท"),
            ("มีค่าธรรมเนียม 10 บาท", "ส่วนลดร้อยละ 10"),
            ("ดำเนินการภายใน 7 วัน", "ดำเนินการภายใน 7 วันทำการ"),
        ):
            with self.subTest(claim=claim), patch.object(chat, "_add_metadata") as enrich:
                answer, _ = await chat._validated_answer(
                    json.dumps({"answer": claim, "sources": [1]}), [{"content": evidence}],
                )
                self.assertEqual(answer, chat.NO_MATCH)
                enrich.assert_not_called()

    async def test_equivalent_numeric_unit_spellings_are_accepted(self):
        for evidence, claim in (
            ("ดำเนินการภายใน ๑ ชม.", "ใช้เวลา **1** ชั่วโมง"),
            ("มีค่าธรรมเนียม ฿ 50", "ค่าธรรมเนียม 50 บาท"),
            ("มีส่วนลดร้อยละ 10", "ส่วนลด 10%"),
            ("ยื่นเอกสารภายใน ๕ วัน ทำการ", "ยื่นได้ภายใน 5 วันทำการ"),
        ):
            with self.subTest(claim=claim):
                answer, _ = await chat._validated_answer(
                    json.dumps({"answer": claim, "sources": [1]}), [{"content": evidence}],
                )
                self.assertIn(claim, answer)

    async def test_repairs_missing_citation_once(self):
        matches = [{"content": "ยื่นได้ที่กองช่าง", "category": "ก่อสร้าง"}]
        for invalid in (
            "invalid JSON",
            '{"answer":"ยื่นที่กองช่าง","sources":[]}',
            '{"answer":"ยื่นที่กองช่าง","sources":[99]}',
        ):
            with (
                self.subTest(invalid=invalid),
                patch.object(chat, "embed_text", AsyncMock(return_value=[0.2])),
                patch.object(chat, "_match", return_value=matches),
                patch.object(chat, "generate_answer", AsyncMock(side_effect=[
                    invalid, '{"answer":"ยื่นที่กองช่าง","sources":[1]}',
                ])) as generate,
            ):
                answer, category = await chat._answer("ขออนุญาตก่อสร้างอาคารที่ไหน", [])
                self.assertIn("ยื่นที่กองช่าง", answer)
                self.assertEqual(category, "ก่อสร้าง")
                self.assertEqual(generate.await_count, 2)
                self.assertEqual(generate.await_args_list[0].args, generate.await_args_list[1].args)

    async def test_repair_cannot_bypass_numeric_guard(self):
        with (
            patch.object(chat, "embed_text", AsyncMock(return_value=[0.2])),
            patch.object(chat, "_match", return_value=[{"content": "ค่าธรรมเนียม 30 บาท"}]),
            patch.object(chat, "_official_answer", return_value=None),
            patch.object(chat, "generate_answer", AsyncMock(side_effect=[
                '{"answer":"ค่าธรรมเนียม 500 บาท","sources":[]}',
                '{"answer":"ค่าธรรมเนียม 500 บาท","sources":[1]}',
            ])) as generate,
        ):
            answer, _ = await chat._answer("ค่าธรรมเนียมกำจัดขยะเท่าไหร่", [])
        self.assertEqual(answer, chat.NO_MATCH)
        self.assertEqual(generate.await_count, 2)

    async def test_abstention_keeps_official_fallback_without_retry(self):
        with (
            patch.object(chat, "embed_text", AsyncMock(return_value=[0.2])),
            patch.object(chat, "_match", return_value=[{"content": "ข้อมูลไม่ตรงคำถาม"}]),
            patch.object(chat, "_official_answer", return_value=("verified", "category")),
            patch.object(chat, "generate_answer", AsyncMock(
                return_value='{"answer":"","sources":[]}',
            )) as generate,
        ):
            result = await chat._answer("ถามข้อมูลเทศบาล", [])
        self.assertEqual(result, ("verified", "category"))
        generate.assert_awaited_once()

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

    async def test_failed_rewrite_searches_latest_user_topic_for_followup(self):
        latest_topic = "ขออนุญาตรื้อถอนอาคารต้องยื่นที่ไหน"
        followup = "ต้องใช้เอกสารอะไรอีก"
        history = [
            {"role": "user", "content": "ขึ้นทะเบียนพาณิชย์ที่ไหน"},
            {"role": "user", "content": latest_topic},
            {"role": "assistant", "content": "ไปกองช่าง"},
            {"role": "user", "content": "แล้วใช้เวลากี่วัน"},
            {"role": "assistant", "content": "ภายใน 5 วัน"},
        ]
        for bad_rewrite in ("   ", "ข้อความ\rคำถาม", followup, ai.AIUnavailable("unavailable")):
            with (
                self.subTest(rewrite=bad_rewrite),
                patch.object(chat, "generate_answer", AsyncMock(side_effect=[
                    bad_rewrite, '{"answer":"ยื่นแบบคำขอ","sources":[1]}',
                ])) as generate,
                patch.object(chat, "embed_text", AsyncMock(return_value=[0.2])) as embed,
                patch.object(chat, "_match", return_value=[{"content": "ให้ยื่นแบบคำขอ"}]),
            ):
                answer, _ = await chat._answer(followup, history)
                embed.assert_awaited_once_with(f"{latest_topic}\n{followup}")
                prompt = json.loads(generate.await_args.args[0])
                self.assertEqual(prompt["question"], followup)
                self.assertIn("ยื่นแบบคำขอ", answer)

    async def test_failed_rewrite_keeps_unrelated_question_standalone(self):
        question = "เทศบาลเปิดกี่โมง"
        with (
            patch.object(chat, "generate_answer", AsyncMock(return_value="")),
            patch.object(chat, "embed_text", AsyncMock(return_value=[0.2])) as embed,
            patch.object(chat, "_match", return_value=[]),
        ):
            await chat._answer(question, [{"role": "user", "content": "ขออนุญาตก่อสร้างอาคารที่ไหน"}])
        embed.assert_awaited_once_with(question)

    async def test_numeric_claim_requires_evidence_within_excerpt_shown_to_model(self):
        matches = [{"content": "ข้อความทั่วไป" * chat.DOCUMENT_EXCERPT_LIMIT + "\nค่าธรรมเนียม 200 บาท"}]
        with patch.object(chat, "_add_metadata") as enrich:
            answer, _ = await chat._validated_answer(
                '{"answer":"ค่าธรรมเนียม 200 บาท","sources":[1]}', matches,
            )
        self.assertEqual(answer, chat.NO_MATCH)
        enrich.assert_not_called()

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

    def test_saved_mode_uses_recent_messages_when_history_read_fails(self):
        app = FastAPI()
        app.state.limiter = chat.limiter
        app.include_router(chat.router)
        session = "11111111-1111-1111-1111-111111111111"
        recent = [{"role": "user", "content": "ขออนุญาตก่อสร้างอาคารที่ไหน"}]
        with (
            TestClient(app) as client,
            patch.object(chat, "_answer", AsyncMock(return_value=("คำตอบ", "บริการ"))) as answer,
            patch.object(chat, "_history", side_effect=RuntimeError("database unavailable")),
            patch.object(chat, "_save_messages", return_value=session) as save,
            patch.object(chat, "_record_analytics"),
            patch.object(chat, "record_usage"),
        ):
            client.cookies.set("session_id", session)
            result = client.post("/chat", json={"message": "ใช้เวลากี่วัน", "no_save": False, "recent": recent})
        self.assertEqual(result.json(), {"answer": "คำตอบ"})
        answer.assert_awaited_once_with("ใช้เวลากี่วัน", recent)
        self.assertEqual(save.call_args.args[0], session)

    async def test_standalone_question_skips_rewrite_call(self):
        question = "ภาษีป้ายต้องจ่ายที่ไหน"
        with (
            patch.object(chat, "generate_answer", AsyncMock(return_value="")) as generate,
            patch.object(chat, "embed_text", AsyncMock(return_value=[0.2])) as embed,
            patch.object(chat, "_match", return_value=[]),
        ):
            await chat._answer(question, [{"role": "user", "content": "ขออนุญาตก่อสร้างอาคารที่ไหน"}])
        generate.assert_not_awaited()
        embed.assert_awaited_once_with(question)

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
