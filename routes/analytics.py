from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from database import supabase
from routes.auth import verify_admin

router = APIRouter(dependencies=[Depends(verify_admin)])
BANGKOK = timezone(timedelta(hours=7), "Asia/Bangkok")
PAGE_SIZE = 500
MAX_DAYS = 366


def _date_range(start: str | None, end: str | None, *, default_days: int = 1) -> tuple[date, date]:
    today = datetime.now(BANGKOK).date()
    try:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise HTTPException(422, "ระบุวันที่ในรูปแบบ YYYY-MM-DD") from exc

    if first is None and last is None:
        return today - timedelta(days=default_days - 1), today
    first = first or last
    last = last or first
    if first == date.min or last == date.max or last < first or (last - first).days >= MAX_DAYS:
        raise HTTPException(422, f"เลือกช่วงวันที่ตามลำดับและไม่เกิน {MAX_DAYS} วัน")
    return first, last


def _utc_midnight(day: date) -> str:
    return datetime.combine(day, time.min, BANGKOK).astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _bangkok_day(value: str) -> date:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(BANGKOK).date()


def _rows(
    table: str,
    fields: str,
    dates: tuple[date, date] | None = None,
    category: str | None = None,
):
    cursor = None
    while True:
        query = supabase.table(table).select(f"id,{fields}").order("id").limit(PAGE_SIZE)
        if dates:
            first, last = dates
            query = query.gte("created_at", _utc_midnight(first)).lt(
                "created_at", _utc_midnight(last + timedelta(days=1))
            )
        if category and category != "all":
            query = query.eq("category", category)
        if cursor is not None:
            query = query.gt("id", cursor)
        rows = query.execute().data or []
        if not rows:
            break
        yield from rows
        cursor = rows[-1]["id"]


def _by_day(rows, dates: tuple[date, date], count_key: str) -> list[dict]:
    counts = Counter(_bangkok_day(row["created_at"]) for row in rows)
    first, last = dates
    days = (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    return [{"date": str(day), count_key: counts[day]} for day in days]


@router.get("/analytics/summary")
def analytics_summary(start: str | None = None, end: str | None = None, category: str | None = None):
    dates = _date_range(start, end)
    counts = Counter(row["category"] for row in _rows("chat_analytics", "category", dates, category))
    return {
        "total_questions": counts.total(),
        "total_users": sum(1 for _ in _rows("chat_sessions", "created_at", dates)),
        "total_categories": sum(bool(key) for key in counts),
    }


@router.get("/analytics/last7days")
def last7days(start: str | None = None, end: str | None = None, category: str | None = None):
    dates = _date_range(start, end, default_days=7)
    return _by_day(_rows("chat_analytics", "created_at", dates, category), dates, "count")


@router.get("/analytics/users")
def users_per_day(start: str | None = None, end: str | None = None):
    dates = _date_range(start, end, default_days=7)
    return _by_day(_rows("chat_sessions", "created_at", dates), dates, "users")


@router.get("/analytics/category-breakdown")
def category_breakdown(start: str | None = None, end: str | None = None):
    dates = _date_range(start, end) if start or end else None
    counts = Counter(row["category"] for row in _rows("chat_analytics", "category", dates) if row["category"])
    return [{"category": name, "count": count} for name, count in counts.most_common()]


@router.get("/analytics/top-questions")
def top_questions(
    limit: int = Query(10, ge=1, le=100),
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
):
    dates = _date_range(start, end) if start or end else None
    counts = Counter(
        row["question"] for row in _rows("chat_analytics", "question", dates, category) if row["question"]
    )
    return [{"question": question, "count": count} for question, count in counts.most_common(limit)]


@router.get("/analytics/categories-list")
def categories_list():
    return sorted({row["category"] for row in _rows("chat_analytics", "category") if row["category"]})
