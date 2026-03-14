import os
import json
import logging
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Upstash Redis (HTTP-based) — ใช้ environment variables จาก Railway
# ---------------------------------------------------------------------------
UPSTASH_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

_upstash_available = bool(UPSTASH_URL and UPSTASH_TOKEN)

if not _upstash_available:
    logger.warning("UPSTASH_REDIS_REST_URL / TOKEN ไม่ได้ตั้งค่า — ใช้ in-memory fallback แทน")

# ---------------------------------------------------------------------------
# In-memory fallback (maxsize=200 ป้องกัน OOM บน Railway free tier 512MB)
# ---------------------------------------------------------------------------
_fallback: TTLCache = TTLCache(maxsize=200, ttl=int(os.environ.get("CACHE_TTL", 300)))


# ---------------------------------------------------------------------------
# Upstash helpers (ใช้ httpx async — ไม่ต้อง redis-py)
# ---------------------------------------------------------------------------
async def _upstash_get(key: str) -> str | None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                f"{UPSTASH_URL}/get/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            )
            data = r.json()
            return data.get("result")  # None ถ้า key ไม่มี
    except Exception as e:
        logger.warning(f"Upstash GET error: {e}")
        return None


async def _upstash_setex(key: str, ttl_seconds: int, value: str) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.post(
                f"{UPSTASH_URL}/setex/{key}/{ttl_seconds}/{value}",
                headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            )
            return r.json().get("result") == "OK"
    except Exception as e:
        logger.warning(f"Upstash SETEX error: {e}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def get_cache(key: str) -> dict | None:
    """คืน {"answer": "..."} หรือ None ถ้า cache miss"""
    if _upstash_available:
        raw = await _upstash_get(key)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                pass

    # fallback
    return _fallback.get(key)


async def set_cache(key: str, answer: str, ttl: int) -> None:
    """บันทึก answer ลง cache พร้อม TTL (วินาที)"""
    payload = json.dumps({"answer": answer}, ensure_ascii=False)

    if _upstash_available:
        ok = await _upstash_setex(key, ttl, payload)
        if ok:
            return  # สำเร็จแล้ว ไม่ต้อง fallback

    # fallback (TTLCache ตั้ง ttl ตอน init แล้ว ไม่ต้องส่ง ttl ซ้ำ)
    _fallback[key] = {"answer": answer}