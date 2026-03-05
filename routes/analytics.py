from fastapi import APIRouter, Depends, Query
from collections import Counter
from datetime import datetime, timedelta

from database import supabase
from routes.auth import verify_admin

router = APIRouter()


# -----------------------
# Summary Dashboard
# -----------------------
@router.get("/analytics/summary")
def get_summary():

    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)

    # คำถามวันนี้
    q = supabase.table("chat_logs")\
        .select("id", count="exact")\
        .gte("created_at", today.isoformat())\
        .lt("created_at", tomorrow.isoformat())\
        .execute()

    total_questions = q.count or 0

    # ผู้ใช้วันนี้ (distinct)
    users = supabase.table("chat_logs")\
        .select("session_id")\
        .gte("created_at", today.isoformat())\
        .lt("created_at", tomorrow.isoformat())\
        .execute()

    unique_users = len(set([u["session_id"] for u in users.data]))

    # หมวดหมู่
    cats = supabase.table("documents")\
        .select("category")\
        .execute()

    categories = len(set([c["category"] for c in cats.data]))

    return {
        "total_questions": total_questions,
        "total_users": unique_users,
        "total_categories": categories
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

        d = datetime.fromisoformat(
            r["created_at"].replace("Z","+00:00")
        ).date()

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

        d = datetime.fromisoformat(
            r["created_at"].replace("Z","+00:00")
        ).date()

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