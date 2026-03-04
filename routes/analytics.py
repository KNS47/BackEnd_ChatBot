from fastapi import APIRouter, Depends
from collections import Counter

from database import supabase
from routes.auth import verify_admin

router = APIRouter()


# -----------------------
# Top Questions
# -----------------------
@router.get("/analytics/top-questions", dependencies=[Depends(verify_admin)])
async def top_questions(limit: int = 10):

    result = supabase.table("chat_analytics") \
        .select("question") \
        .execute()

    if not result.data:
        return {"data": []}

    questions = [row["question"] for row in result.data]

    counter = Counter(questions)
    most_common = counter.most_common(limit)

    return {
        "data": [
            {"question": q, "count": c}
            for q, c in most_common
        ]
    }


# -----------------------
# Category Stats
# -----------------------
@router.get("/analytics/categories", dependencies=[Depends(verify_admin)])
async def category_stats():

    result = supabase.table("chat_analytics") \
        .select("category") \
        .execute()

    if not result.data:
        return {"data": []}

    categories = [row["category"] for row in result.data]

    counter = Counter(categories)

    return {
        "data": [
            {"category": cat, "count": count}
            for cat, count in counter.items()
        ]
    }


# -----------------------
# Total Sessions
# -----------------------
@router.get("/analytics/sessions", dependencies=[Depends(verify_admin)])
async def total_sessions():

    result = supabase.table("chat_sessions") \
        .select("id") \
        .execute()

    total = len(result.data) if result.data else 0

    return {"total_sessions": total}