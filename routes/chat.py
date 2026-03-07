from fastapi import APIRouter, Request, Cookie
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from time import time
from collections import Counter

from slowapi import Limiter
from slowapi.util import get_remote_address

from database import supabase
from ai import embed_text, generate_answer
from config import CACHE_TTL
from middleware import limiter

router = APIRouter()

response_cache = {}

def parse_dt(ts: str) -> "datetime":
    """แก้ปัญหา Python 3.10 ไม่รองรับ microseconds ที่ไม่ครบ 6 หลัก"""
    ts = ts.replace("Z", "+00:00")
    if "." in ts:
        dot_idx = ts.index(".")
        plus_idx = ts.find("+", dot_idx)
        frac = ts[dot_idx+1:plus_idx if plus_idx != -1 else len(ts)]
        frac = frac.ljust(6, "0")[:6]
        tz = ts[plus_idx:] if plus_idx != -1 else ""
        ts = ts[:dot_idx+1] + frac + tz
    return datetime.fromisoformat(ts)

# -----------------------
# Chat History
# -----------------------
@router.get("/chat/history")
async def get_chat_history(session_id: str = Cookie(default=None)):
    if not session_id:
        return {"history": []}
    
    check = supabase.table("chat_sessions").select("id").eq("id", session_id).execute()
    if not check.data:
        return {"history": []}

    result = supabase.table("chat_messages") \
        .select("role, content") \
        .eq("session_id", session_id) \
        .order("created_at", desc=False) \
        .execute()
    
    return {"history": result.data}


# -----------------------
# Clear Session
# -----------------------
@router.post("/chat/clear-session")
async def clear_session(session_id: str = Cookie(default=None)):
    if session_id:
        supabase.table("chat_messages").delete().eq("session_id", session_id).execute()
        supabase.table("chat_summaries").delete().eq("session_id", session_id).execute()
        # ไม่ลบ chat_analytics เพื่อให้แอดมินยังดูสถิติได้

    resp = JSONResponse({"cleared": True})
    resp.delete_cookie(key="session_id", path="/", samesite="none", secure=True)
    return resp


# -----------------------
# Chat Endpoint
# -----------------------
@router.post("/chat")
@limiter.limit("20/minute")
async def chat(request: Request, session_id: str = Cookie(default=None)):

    now = datetime.utcnow()

    # Session timeout (30 นาที) — เมื่อหมดอายุลบประวัติแชท แต่คง analytics ไว้
    if session_id:
        last_msg = supabase.table("chat_messages") \
            .select("created_at") \
            .eq("session_id", session_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if last_msg.data:
            last_time = parse_dt(last_msg.data[0]["created_at"])
            if now - last_time.replace(tzinfo=None) > timedelta(minutes=30):
                supabase.table("chat_messages").delete().eq("session_id", session_id).execute()
                supabase.table("chat_summaries").delete().eq("session_id", session_id).execute()
                session_id = None

    # Create new session if needed
    if not session_id:
        session = supabase.table("chat_sessions").insert({}).execute()
        session_id = session.data[0]["id"]

    try:
        body = await request.json()
        question = body.get("message", "").strip()

        if not question:
            return {"answer": "กรุณาพิมพ์คำถามก่อนส่งค่ะ"}

        if len(question) > 500:
            return {"answer": "ข้อความยาวเกินไป กรุณาส่งไม่เกิน 500 ตัวอักษรค่ะ"}

        # Validate session
        check = supabase.table("chat_sessions").select("id").eq("id", session_id).execute()
        if not check.data:
            session = supabase.table("chat_sessions").insert({}).execute()
            session_id = session.data[0]["id"]

        # -----------------------
        # Cache (per session)
        # -----------------------
        cache_key = f"{session_id}:{question.lower()}"
        now_ts = time()

        expired = [
            k for k, v in response_cache.items()
            if now_ts - v["timestamp"] > CACHE_TTL
        ]
        for k in expired:
            del response_cache[k]

        if cache_key in response_cache:
            resp = JSONResponse({"answer": response_cache[cache_key]["answer"]})
            resp.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                secure=True,
                samesite="none"
            )
            return resp

        # จะบันทึก user message เฉพาะเมื่อพบเอกสารที่เกี่ยวข้อง (ด้านล่าง)

        # Get history
        history_result = supabase.table("chat_messages") \
            .select("role,content") \
            .eq("session_id", session_id) \
            .order("created_at", desc=False) \
            .execute()

        history = history_result.data or []

        # -----------------------
        # Summary if long
        # -----------------------
        summary = ""
        if len(history) > 12:
            conversation_text = "\n".join(
                [f"{m['role']}: {m['content']}" for m in history]
            )

            summary_prompt = f"""สรุปบทสนทนานี้ให้สั้น กระชับ และเก็บประเด็นสำคัญ:

{conversation_text}"""

            summary = generate_answer(summary_prompt)

            supabase.table("chat_summaries").upsert({
                "session_id": session_id,
                "summary": summary
            }).execute()

        if len(history) > 10:
            history = history[-10:]

        history_text = "\n".join(
            [f"{m['role']}: {m['content']}" for m in history]
        )

        # -----------------------
        # Rewrite Question
        # -----------------------
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

            rewritten_question = generate_answer(rewrite_prompt).strip()
            # ถ้า rewrite ออกมายาวผิดปกติ หรือดูไม่เหมือนคำถาม ให้ใช้ต้นฉบับ
            if len(rewritten_question) > 300 or "\n" in rewritten_question:
                rewritten_question = question

        # -----------------------
        # RAG
        # -----------------------
        question_embedding = embed_text(rewritten_question)

        result = supabase.rpc("match_documents", {
            "query_embedding": question_embedding,
            "match_threshold": 0.7,
            "match_count": 5
        }).execute()

        matches = result.data
        if not matches:
            # ตรวจว่าเป็นคำทักทาย/สนทนาทั่วไปหรือเปล่า
            greeting_check = generate_answer(
                f"""ประโยคนี้เป็นคำทักทาย กล่าวลา หรือสนทนาทั่วไป (เช่น สวัสดี ขอบคุณ ทำไรได้บ้าง) ใช่หรือไม่?\nตอบแค่ YES หรือ NO\nประโยค: {question}"""
            ).strip().upper()

            if greeting_check.startswith("YES"):
                answer = generate_answer(
                    f"""คุณคือแชทบอทเทศบาล เป็นบอทผู้หญิงที่คอยช่วยตอบคำถามให้กับประชาชน\nตอบคำทักทายหรือสนทนาทั่วไปนี้อย่างสุภาพ เป็นมิตร และแนะนำว่าสามารถช่วยตอบคำถามเกี่ยวกับข้อมูลเทศบาลได้\nไม่ต้องสวัสดีซ้ำถ้าทักทายไปแล้ว\nคำถาม: {rewritten_question}"""
                )
            else:
                answer = "ขออภัยค่ะ ไม่พบข้อมูลในเอกสารที่เกี่ยวข้องกับคำถามนี้ หากต้องการสอบถามเพิ่มเติม สามารถติดต่อเจ้าหน้าที่เทศบาลได้โดยตรงค่ะ"

            resp = JSONResponse({"answer": answer})
            resp.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                secure=True,
                samesite="none"
            )
            return resp
        categories = list(set([
            m["category"] for m in matches if m.get("category")
        ]))

        main_category = categories[0] if categories else "อื่น ๆ"

        context = "\n".join(
            [m["content"] for m in matches]
        ) if matches else ""

        if summary:
            context = f"สรุปบทสนทนาก่อนหน้า:\n{summary}\n\n" + context

        extra_context = (
            f"บทสนทนาก่อนหน้า:\n{history_text}\n\n"
            if history_text else ""
        )

        prompt = f"""คุณคือแชทบอทเทศบาล เป็นบอทผู้หญิงที่คอยช่วยตอบคำถามให้กับประชาชนที่เข้ามาสอบถาม
กติกาสำคัญ:
- ให้ใช้ข้อมูลจาก "ข้อมูลเอกสาร" เป็นหลักในการตอบ
- สามารถใช้ "บทสนทนาก่อนหน้า" เพื่อทำความเข้าใจคำถามอ้างอิง
- ห้ามแต่งข้อมูลที่ไม่มีในข้อมูลเอกสาร
- ถ้าไม่มีข้อมูลจริง ๆ ให้ตอบว่า ไม่พบข้อมูล
- ตอบเป็น Markdown ได้ (ใช้ ตัวหนา, ถ้าเป็นรายการใช้ - ได้)

ข้อมูลเอกสาร:
{context}

{extra_context}
คำแนะนำ:
1. ถ้าเป็นคำทักทายหรือกล่าวลา ตอบอย่างสุภาพและเป็นมิตร
2. ตอบให้กระชับและเป็นกันเอง
3. ไม่ต้องสวัสดีทุกรอบ
4. แทน User ว่า "คุณ" เสมอ
5. ห้ามตอบเรื่องศาสนา การเมือง พระมหากษัตริย์
6. ถ้าไม่มีข้อมูลจริง ๆ ให้ตอบว่า ไม่พบข้อมูล

คำถาม: {rewritten_question}"""

        answer = generate_answer(prompt)

        # Cache answer
        response_cache[cache_key] = {
            "answer": answer,
            "timestamp": time()
        }

        # -----------------------
        # Analytics
        # -----------------------
        last_cat_result = supabase.table("chat_analytics") \
            .select("category") \
            .eq("session_id", session_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        last_cat = (
            last_cat_result.data[0]["category"]
            if last_cat_result.data else None
        )

        if not last_cat or last_cat != main_category:
            supabase.table("chat_analytics").insert({
                "session_id": session_id,
                "question": question,
                "category": main_category
            }).execute()

        # บันทึก user และ assistant message เฉพาะเมื่อพบเอกสาร
        supabase.table("chat_messages").insert({
            "session_id": session_id,
            "role": "user",
            "content": question
        }).execute()
        supabase.table("chat_messages").insert({
            "session_id": session_id,
            "role": "assistant",
            "content": answer
        }).execute()

        resp = JSONResponse({"answer": answer})
        resp.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=True,
            samesite="none"
        )
        return resp

    except Exception as e:
        print("CHAT ERROR:", e)
        return {"error": "เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้งค่ะ"}