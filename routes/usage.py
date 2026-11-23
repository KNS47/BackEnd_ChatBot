import logging
import os

from fastapi import APIRouter, Depends

from database import supabase
from pdf_service import BUCKET_NAME
from routes.auth import verify_admin

logger = logging.getLogger(__name__)
router = APIRouter()

def record_usage(questions: int, tokens: int) -> None:
    try:
        supabase.rpc("record_municipal_usage", {
            "question_delta": questions, "token_delta": tokens,
        }).execute()
    except Exception as error:
        logger.warning("Usage tally unavailable: %s", type(error).__name__)


def _limit(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if len(value) <= 15 and value.isascii() and value.isdecimal() and int(value) > 0 else None


@router.get("/api/admin/usage", dependencies=[Depends(verify_admin)])
def admin_usage():
    result = {}
    try:
        response = supabase.rpc("municipal_usage_snapshot", {"pdf_bucket": BUCKET_NAME}).execute()
        result = (response.data or [{}])[0]
    except Exception as error:
        logger.warning("Usage snapshot unavailable: %s", type(error).__name__)
    return {
        "today": {"questions": result.get("questions"), "tokens": result.get("tokens")},
        "limits": {
            "questions": _limit("ADMIN_DAILY_QUESTION_LIMIT"),
            "tokens": _limit("ADMIN_DAILY_TOKEN_LIMIT"),
            "storage_bytes": _limit("ADMIN_STORAGE_LIMIT_BYTES"),
        },
        "storage": {"used_bytes": result.get("used_bytes")},
        "durable": bool(result),
    }
