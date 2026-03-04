from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from config import ADMIN_USER, ADMIN_PASS

router = APIRouter()


# -----------------------
# Verify Admin Dependency
# -----------------------
def verify_admin(request: Request):
    admin = request.session.get("admin")

    if not admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return admin


# -----------------------
# Login
# -----------------------
@router.post("/api/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):

    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["admin"] = username
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

    request.session.clear()

    return {"success": True}