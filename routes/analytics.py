from fastapi import APIRouter, Depends, Query
from collections import Counter
from datetime import datetime, timedelta

from database import supabase
from routes.auth import verify_admin

router = APIRouter()

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
# Summary Dashboard
# -----------------------
@router.get("/analytics/summary", dependencies=[Depends(verify_admin)])
async def analytics_summary(
    start: str = Query(None),
    end: str = Query(None)
):
    q = supabase.table("chat_analytics").select("category, created_at").execute()
    sessions = supabase.table("chat_sessions").select("id, created_at").execute()

    data = q.data or []
    session_data = sessions.data or []

    today = datetime.utcnow().date()

    # ถ้าไม่ได้เลือก filter ให้ใช้วันนี้ ถ้าเลือกให้ใช้ช่วงที่เลือก
    try:
        date_start = datetime.strptime(start, "%Y-%m-%d").date() if start else today
        date_end = datetime.strptime(end, "%Y-%m-%d").date() if end else today
    except ValueError:
        date_start = date_end = today

    filtered_questions = [
        r for r in data
        if r.get("created_at") and
        date_start <= parse_dt(r["created_at"]).date() <= date_end
    ]

    filtered_users = {
        r["id"]
        for r in session_data
        if r.get("created_at") and
        date_start <= parse_dt(r["created_at"]).date() <= date_end
    }

    categories = set([r["category"] for r in data if r.get("category")])

    return {
        "total_questions": len(filtered_questions),
        "total_users": len(filtered_users),
        "total_categories": len(categories)
    }


# -----------------------
# Questions Trend (7 days)
# -----------------------
@router.get("/analytics/last7days", dependencies=[Depends(verify_admin)])
async def last7days():

    result = supabase.table("chat_analytics") \
        .select("created_at") \
        .execute()

    rows = result.data or []

    today = datetime.utcnow().date()

    counts = { (today - timedelta(days=i)):0 for i in range(7) }

    for r in rows:
        if not r.get("created_at"):
            continue

        d = parse_dt(r["created_at"]).date()

        if d in counts:
            counts[d] += 1

    return [
        {"date": str(d), "count": counts[d]}
        for d in sorted(counts)
    ]


# -----------------------
# Users per day
# -----------------------
@router.get("/analytics/users", dependencies=[Depends(verify_admin)])
async def users_per_day():

    result = supabase.table("chat_sessions") \
        .select("id, created_at") \
        .execute()

    rows = result.data or []

    today = datetime.utcnow().date()
    counts = { (today - timedelta(days=i)):0 for i in range(7) }

    for r in rows:
        if not r.get("created_at"):
            continue

        d = parse_dt(r["created_at"]).date()

        if d in counts:
            counts[d] += 1

    return [
        {"date": str(d), "users": counts[d]}
        for d in sorted(counts)
    ]


# -----------------------
# Category Breakdown
# -----------------------
@router.get("/analytics/category-breakdown", dependencies=[Depends(verify_admin)])
async def category_breakdown():

    result = supabase.table("chat_analytics") \
        .select("category") \
        .execute()

    rows = result.data or []

    categories = [r["category"] for r in rows if r.get("category")]

    counter = Counter(categories)

    return [
        {"category": c, "count": n}
        for c,n in counter.items()
    ]


# -----------------------
# Top Questions
# -----------------------
@router.get("/analytics/top-questions", dependencies=[Depends(verify_admin)])
async def top_questions(limit: int = 10):

    result = supabase.table("chat_analytics") \
        .select("question") \
        .execute()

    rows = result.data or []

    questions = [r["question"] for r in rows if r.get("question")]

    counter = Counter(questions)

    return [
        {"question": q, "count": c}
        for q,c in counter.most_common(limit)
    ]


# -----------------------
# Categories List
# -----------------------
@router.get("/analytics/categories-list", dependencies=[Depends(verify_admin)])
async def categories_list():

    result = supabase.table("chat_analytics") \
        .select("category") \
        .execute()

    rows = result.data or []

    categories = list(set([
        r["category"] for r in rows if r.get("category")
    ]))

    return categories