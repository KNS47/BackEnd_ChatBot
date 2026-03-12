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


def get_date_range(start: str, end: str):
    """แปลง start/end string เป็น date object พร้อม fallback"""
    today = datetime.utcnow().date()
    try:
        date_start = datetime.strptime(start, "%Y-%m-%d").date() if start else today
        date_end = datetime.strptime(end, "%Y-%m-%d").date() if end else today
    except ValueError:
        date_start = date_end = today
    return date_start, date_end


# -----------------------
# Summary Dashboard
# -----------------------
@router.get("/analytics/summary", dependencies=[Depends(verify_admin)])
async def analytics_summary(
    start: str = Query(None),
    end: str = Query(None),
    category: str = Query(None)
):
    q = supabase.table("chat_analytics").select("category, created_at").execute()
    sessions = supabase.table("chat_sessions").select("id, created_at").execute()

    data = q.data or []
    session_data = sessions.data or []

    date_start, date_end = get_date_range(start, end)

    filtered_questions = [
        r for r in data
        if r.get("created_at") and
        date_start <= parse_dt(r["created_at"]).date() <= date_end and
        (not category or category == "all" or r.get("category") == category)
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
# Questions Trend (by date range, default 7 days)
# -----------------------
@router.get("/analytics/last7days", dependencies=[Depends(verify_admin)])
async def last7days(
    start: str = Query(None),
    end: str = Query(None),
    category: str = Query(None)
):
    result = supabase.table("chat_analytics") \
        .select("created_at, category") \
        .execute()

    rows = result.data or []

    today = datetime.utcnow().date()
    date_start, date_end = get_date_range(start, end)

    # ถ้าไม่มี filter ให้แสดง 7 วันย้อนหลัง
    if not start and not end:
        date_start = today - timedelta(days=6)
        date_end = today

    num_days = (date_end - date_start).days + 1
    counts = {date_start + timedelta(days=i): 0 for i in range(num_days)}

    for r in rows:
        if not r.get("created_at"):
            continue
        if category and category != "all" and r.get("category") != category:
            continue
        d = parse_dt(r["created_at"]).date()
        if d in counts:
            counts[d] += 1

    return [
        {"date": str(d), "count": counts[d]}
        for d in sorted(counts)
    ]


# -----------------------
# Users per day (by date range, default 7 days)
# -----------------------
@router.get("/analytics/users", dependencies=[Depends(verify_admin)])
async def users_per_day(
    start: str = Query(None),
    end: str = Query(None)
):
    result = supabase.table("chat_sessions") \
        .select("id, created_at") \
        .execute()

    rows = result.data or []

    today = datetime.utcnow().date()
    date_start, date_end = get_date_range(start, end)

    if not start and not end:
        date_start = today - timedelta(days=6)
        date_end = today

    num_days = (date_end - date_start).days + 1
    counts = {date_start + timedelta(days=i): 0 for i in range(num_days)}

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
# Category Breakdown (by date range)
# -----------------------
@router.get("/analytics/category-breakdown", dependencies=[Depends(verify_admin)])
async def category_breakdown(
    start: str = Query(None),
    end: str = Query(None)
):
    result = supabase.table("chat_analytics") \
        .select("category, created_at") \
        .execute()

    rows = result.data or []

    date_start, date_end = get_date_range(start, end)

    # ถ้าไม่มี filter ให้แสดงทั้งหมด
    if start or end:
        rows = [
            r for r in rows
            if r.get("created_at") and
            date_start <= parse_dt(r["created_at"]).date() <= date_end
        ]

    categories = [r["category"] for r in rows if r.get("category")]
    counter = Counter(categories)

    return [
        {"category": c, "count": n}
        for c, n in counter.most_common()
    ]


# -----------------------
# Top Questions (by date range + category)
# -----------------------
@router.get("/analytics/top-questions", dependencies=[Depends(verify_admin)])
async def top_questions(
    limit: int = 10,
    start: str = Query(None),
    end: str = Query(None),
    category: str = Query(None)
):
    result = supabase.table("chat_analytics") \
        .select("question, category, created_at") \
        .execute()

    rows = result.data or []

    date_start, date_end = get_date_range(start, end)

    filtered = []
    for r in rows:
        if not r.get("question"):
            continue
        if start or end:
            if not r.get("created_at"):
                continue
            if not (date_start <= parse_dt(r["created_at"]).date() <= date_end):
                continue
        if category and category != "all" and r.get("category") != category:
            continue
        filtered.append(r["question"])

    counter = Counter(filtered)

    return [
        {"question": q, "count": c}
        for q, c in counter.most_common(limit)
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

    categories = sorted(list(set([
        r["category"] for r in rows if r.get("category")
    ])))

    return categories