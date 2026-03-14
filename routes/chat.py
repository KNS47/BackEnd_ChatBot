from fastapi import APIRouter, Request, Cookie
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta

from database import supabase
from ai import embed_text, generate_answer
from config import CACHE_TTL
from middleware import limiter
from cache import get_cache, set_cache

router = APIRouter()

COMPLAINT_URL = "https://www.sila-kk.go.th/link.php?menuid=11"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_dt(ts: str) -> datetime:
    """แก้ปัญหา Python 3.10 ไม่รองรับ microseconds ที่ไม่ครบ 6 หลัก"""
    ts = ts.replace("Z", "+00:00")
    if "." in ts:
        dot_idx = ts.index(".")
        plus_idx = ts.find("+", dot_idx)
        frac = ts[dot_idx + 1 : plus_idx if plus_idx != -1 else len(ts)]
        frac = frac.ljust(6, "0")[:6]
        tz = ts[plus_idx:] if plus_idx != -1 else ""
        ts = ts[: dot_idx + 1] + frac + tz
    return datetime.fromisoformat(ts)


def _set_session_cookie(resp: JSONResponse, session_id: str) -> JSONResponse:
    resp.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=True,
        samesite="none",
    )
    return resp


def _delete_session_cookie(resp: JSONResponse) -> JSONResponse:
    resp.delete_cookie(key="session_id", path="/", samesite="none", secure=True)
    return resp


def _format_chunk(m: dict) -> str:
    """
    รวม content + URL จาก document chunk เข้าด้วยกัน
    เพื่อให้ LLM เห็น URL จริงและไม่แต่งขึ้นมาเอง
    ปรับชื่อ field ให้ตรงกับ Supabase table ของคุณ (url / source / link)
    """
    parts = [m["content"]]
    url = (
        m.get("url")
        or m.get("source")
        or m.get("link")
        or (m.get("metadata") or {}).get("url")
    )
    if url:
        parts.append(f"ลิงก์อ้างอิง: {url}")
    return "\n".join(parts)


def _is_session_expired(session_id: str, now: datetime) -> bool:
    """คืน True ถ้า session idle เกิน 10 นาที"""
    last_msg = (
        supabase.table("chat_messages")
        .select("created_at")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not last_msg.data:
        return False  # session ใหม่ ยังไม่มีข้อความ
    last_time = parse_dt(last_msg.data[0]["created_at"])
    return now - last_time.replace(tzinfo=None) > timedelta(minutes=10)


# ---------------------------------------------------------------------------
# GET /chat/history
# ---------------------------------------------------------------------------
@router.get("/chat/history")
async def get_chat_history(session_id: str = Cookie(default=None)):
    if not session_id:
        return {"history": []}

    now = datetime.utcnow()

    if _is_session_expired(session_id, now):
        resp = JSONResponse({"history": [], "session_expired": True})
        return _delete_session_cookie(resp)

    check = supabase.table("chat_sessions").select("id").eq("id", session_id).execute()
    if not check.data:
        return {"history": []}

    result = (
        supabase.table("chat_messages")
        .select("role, content, created_at")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .execute()
    )
    return {"history": result.data}


# ---------------------------------------------------------------------------
# GET /health  — keep-alive ping สำหรับ cron-job.org (ป้องกัน Railway sleep)
# ---------------------------------------------------------------------------
@router.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------
@router.post("/chat")
@limiter.limit("20/minute")
async def chat(request: Request, session_id: str = Cookie(default=None)):
    now = datetime.utcnow()

    # ── Session timeout ──────────────────────────────────────────────────────
    if session_id and _is_session_expired(session_id, now):
        session_id = None
        resp = JSONResponse({"session_expired": True})
        return _delete_session_cookie(resp)

    # ── สร้าง / validate session ─────────────────────────────────────────────
    if not session_id:
        session = supabase.table("chat_sessions").insert({}).execute()
        session_id = session.data[0]["id"]
    else:
        check = (
            supabase.table("chat_sessions").select("id").eq("id", session_id).execute()
        )
        if not check.data:
            session = supabase.table("chat_sessions").insert({}).execute()
            session_id = session.data[0]["id"]

    try:
        body = await request.json()
        question = body.get("message", "").strip()

        if not question:
            return {"answer": "กรุณาพิมพ์คำถามก่อนส่งค่ะ"}

        if len(question) > 500:
            return {"answer": "ข้อความยาวเกินไป กรุณาส่งไม่เกิน 500 ตัวอักษรค่ะ"}

        # ── Cache ────────────────────────────────────────────────────────────
        cache_key = f"{session_id}:{question.lower().strip()}"
        cached = await get_cache(cache_key)
        if cached:
            resp = JSONResponse({"answer": cached["answer"]})
            return _set_session_cookie(resp, session_id)

        # ── History ──────────────────────────────────────────────────────────
        history_result = (
            supabase.table("chat_messages")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
        history = history_result.data or []

        # ── Summary (สร้างเมื่อยาว และยังไม่มีใน DB — ไม่ call LLM ซ้ำทุก req) ──
        summary = ""
        if len(history) > 12:
            existing_summary = (
                supabase.table("chat_summaries")
                .select("summary")
                .eq("session_id", session_id)
                .execute()
            )
            if existing_summary.data:
                summary = existing_summary.data[0]["summary"]
            else:
                conversation_text = "\n".join(
                    f"{m['role']}: {m['content']}" for m in history
                )
                summary_prompt = (
                    f"สรุปบทสนทนานี้ให้สั้น กระชับ และเก็บประเด็นสำคัญ:\n\n{conversation_text}"
                )
                summary = await generate_answer(summary_prompt)
                supabase.table("chat_summaries").upsert(
                    {"session_id": session_id, "summary": summary}
                ).execute()

        # ตัด history เหลือ 10 รายการล่าสุด
        if len(history) > 10:
            history = history[-10:]

        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)

        # ── Rewrite question ─────────────────────────────────────────────────
        rewritten_question = question
        if history_text:
            rewrite_prompt = f"""คุณคือผู้ช่วยที่เชี่ยวชาญการทำความเข้าใจบทสนทนา
งานของคุณคือเขียนคำถามล่าสุดใหม่ให้ครบถ้วนและค้นหาได้ โดยใส่ context จากบทสนทนาก่อนหน้าเข้าไปด้วย

กติกา:
- ตอบเป็นคำถามเดียว ไม่ต้องอธิบาย
- เก็บความหมายเดิมไว้ครบ อย่าเปลี่ยนความหมาย
- ถ้าคำถามอ้างถึง "เขา" "นั้น" "ที่พูดถึง" ให้ระบุชื่อ/สิ่งนั้นให้ชัดเจน
- ถ้าคำถามชัดเจนอยู่แล้ว ให้คืนคำถามเดิม

บทสนทนาก่อนหน้า:
{history_text}

คำถามล่าสุด: {question}

คำถามที่เขียนใหม่:"""
            rewritten_question = (await generate_answer(rewrite_prompt)).strip()
            if len(rewritten_question) > 300 or "\n" in rewritten_question:
                rewritten_question = question

        # ── RAG ──────────────────────────────────────────────────────────────
        question_embedding = await embed_text(rewritten_question)

        result = supabase.rpc(
            "match_documents",
            {
                "query_embedding": question_embedding,
                "match_threshold": 0.6,
                "match_count": 8,
            },
        ).execute()
        matches = result.data or []

        # ── ไม่มีผลลัพธ์จาก RAG ─────────────────────────────────────────────
        if not matches:
            greeting_check = (
                await generate_answer(
                    f"ประโยคนี้เป็นคำทักทาย กล่าวลา หรือสนทนาทั่วไป (เช่น สวัสดี ขอบคุณ ทำไรได้บ้าง) ใช่หรือไม่?\n"
                    f"ตอบแค่ YES หรือ NO\nประโยค: {question}"
                )
            ).strip().upper()

            if greeting_check.startswith("YES"):
                answer = await generate_answer(
                    f"คุณคือแชทบอทเทศบาล เป็นบอทผู้หญิงที่คอยช่วยตอบคำถามให้กับประชาชน\n"
                    f"ตอบคำทักทายหรือสนทนาทั่วไปนี้อย่างสุภาพ เป็นมิตร และแนะนำว่าสามารถช่วยตอบคำถามเกี่ยวกับข้อมูลเทศบาลได้\n"
                    f"ไม่ต้องสวัสดีซ้ำถ้าทักทายไปแล้ว\nคำถาม: {rewritten_question}"
                )
            else:
                answer = "ขออภัยค่ะ ไม่พบข้อมูลในเอกสารที่เกี่ยวข้องกับคำถามนี้ หากต้องการสอบถามเพิ่มเติม สามารถติดต่อเจ้าหน้าที่เทศบาลได้โดยตรงค่ะ"

            resp = JSONResponse({"answer": answer})
            return _set_session_cookie(resp, session_id)

        # ── สร้าง context พร้อม URL ──────────────────────────────────────────
        categories = list({m["category"] for m in matches if m.get("category")})
        main_category = categories[0] if categories else "อื่น ๆ"

        # _format_chunk รวม content + URL จาก Supabase (แก้ปัญหา URL ผิด)
        context = "\n\n---\n".join(_format_chunk(m) for m in matches)

        if summary:
            context = f"สรุปบทสนทนาก่อนหน้า:\n{summary}\n\n" + context

        extra_context = (
            f"บทสนทนาก่อนหน้า:\n{history_text}\n\n" if history_text else ""
        )

        prompt = f"""คุณคือแชทบอทเทศบาล เป็นบอทผู้หญิงที่คอยช่วยตอบคำถามให้กับประชาชนที่เข้ามาสอบถาม คุณไม่มีชื่อจริง แต่ถ้าถามให้แนะนำตัว ให้บอกว่าเป็น "แชทบอทเทศบาล" และสามารถช่วยตอบคำถามเกี่ยวกับข้อมูลเทศบาลได้

กติกาสำคัญ:
- ให้ใช้ข้อมูลจาก "ข้อมูลเอกสาร" เป็นหลักในการตอบ
- สามารถใช้ "บทสนทนาก่อนหน้า" เพื่อทำความเข้าใจคำถามอ้างอิง
- ห้ามแต่งข้อมูลที่ไม่มีในข้อมูลเอกสาร
- ถ้าไม่มีข้อมูลจริง ๆ ให้ตอบว่า "ไม่พบข้อมูล"
- URL ที่ถูกต้องจะอยู่ในบรรทัด "ลิงก์อ้างอิง:" ใน "ข้อมูลเอกสาร" เท่านั้น ห้ามเปลี่ยน ห้ามสร้าง URL ใหม่เด็ดขาด ถ้าไม่มีบรรทัด "ลิงก์อ้างอิง:" ให้บอกว่า "ไม่มีลิงก์ในข้อมูล"
- ถ้าเป็นคำถามเกี่ยวกับการแจ้งเรื่องร้องเรียน ให้ใช้ลิงก์นี้เท่านั้น: {COMPLAINT_URL} ห้ามใช้ลิงก์อื่น
- ตอบเป็น Markdown ได้ (ใช้ **ตัวหนา**, รายการใช้ - ได้)

ข้อมูลเอกสาร:
{context}

{extra_context}คำแนะนำ:
1. ถ้าเป็นคำทักทายหรือกล่าวลา ตอบอย่างสุภาพและเป็นมิตร
2. ตอบให้กระชับและเป็นกันเอง
3. ไม่ต้องสวัสดีทุกรอบ
4. แทน User ว่า "คุณ" เสมอ
5. ห้ามตอบเรื่องศาสนา การเมือง พระมหากษัตริย์
6. ถ้าไม่มีข้อมูลจริง ๆ ให้ตอบว่า "ไม่พบข้อมูล"

คำถาม: {rewritten_question}"""

        answer = await generate_answer(prompt)

        # ── Cache + บันทึก DB ────────────────────────────────────────────────
        await set_cache(cache_key, answer, CACHE_TTL)

        supabase.table("chat_messages").insert(
            {"session_id": session_id, "role": "user", "content": question}
        ).execute()

        supabase.table("chat_analytics").insert(
            {"session_id": session_id, "question": question, "category": main_category}
        ).execute()

        supabase.table("chat_messages").insert(
            {"session_id": session_id, "role": "assistant", "content": answer}
        ).execute()

        resp = JSONResponse({"answer": answer})
        return _set_session_cookie(resp, session_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        print("CHAT ERROR:", e)
        return {"error": "เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้งค่ะ"}