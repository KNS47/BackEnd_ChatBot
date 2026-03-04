from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

limiter = Limiter(key_func=get_remote_address)

async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"error": "คุณส่งข้อความถี่เกินไป กรุณารอสักครู่"}
    )