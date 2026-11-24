import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse


def _proxy_hops() -> int:
    try:
        return max(0, int(os.getenv("TRUSTED_PROXY_HOPS", "0")))
    except ValueError:
        return 0


# Number of trusted proxies in front of the app (Render: 1). Each proxy appends the
# address it received the request from to X-Forwarded-For, so the client IP is the
# entry PROXY_HOPS from the right. Entries further left are client-supplied and are
# never trusted, so they cannot be spoofed to dodge the rate limit.
PROXY_HOPS = _proxy_hops()


def client_ip(request) -> str:
    if PROXY_HOPS:
        hops = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if len(hops) >= PROXY_HOPS:
            return hops[-PROXY_HOPS]
    return get_remote_address(request)


limiter = Limiter(key_func=client_ip)

async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"error": "คุณส่งข้อความถี่เกินไป กรุณารอสักครู่"}
    )
