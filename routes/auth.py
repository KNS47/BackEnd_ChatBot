from hmac import compare_digest, digest
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse
from config import ADMIN_USER, ADMIN_PASS, COOKIE_SECURE, FRONTEND_ORIGINS, SESSION_SECRET
from middleware import limiter

router = APIRouter()

ADMIN_SESSION_MAX_AGE = 8 * 60 * 60


def _credential_stamp() -> str:
    credentials = "\0".join((ADMIN_USER, ADMIN_PASS))
    return digest(SESSION_SECRET.encode(), credentials.encode(), "sha256").hex()


def current_admin(request: Request) -> str | None:
    if not ADMIN_USER or not ADMIN_PASS or request.session.get("admin") != ADMIN_USER:
        return None
    stamp = request.session.get("credential_stamp")
    if not isinstance(stamp, str) or not compare_digest(stamp, _credential_stamp()):
        return None
    return ADMIN_USER


def _require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    scheme = "https" if COOKIE_SECURE else request.url.scheme
    host_origin = f"{scheme}://{request.url.netloc}"
    if origin and origin != host_origin and origin not in FRONTEND_ORIGINS:
        raise HTTPException(status_code=403, detail="Untrusted request origin")


# -----------------------
# Verify Admin Dependency
# -----------------------
def verify_admin(request: Request):
    admin = current_admin(request)

    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _require_trusted_origin(request)
    return admin


# -----------------------
# Login
# -----------------------
@router.post("/api/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    _require_trusted_origin(request)

    if (
        ADMIN_USER and ADMIN_PASS
        and compare_digest(username.encode(), ADMIN_USER.encode())
        and compare_digest(password.encode(), ADMIN_PASS.encode())
    ):
        request.session.update(admin=username, credential_stamp=_credential_stamp())
        return {"success": True}

    return JSONResponse(
        status_code=401,
        content={"success": False, "message": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"}
    )


# -----------------------
# Logout
# -----------------------
@router.post("/api/logout")
async def logout(request: Request):

    _require_trusted_origin(request)
    request.session.clear()

    return {"success": True}
