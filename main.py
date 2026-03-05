from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from middleware import limiter, rate_limit_handler
from slowapi.errors import RateLimitExceeded
from config import SESSION_SECRET, FRONTEND_URL

from routes import auth, chat, pdf, analytics

app = FastAPI()

# 1. จัดการเรื่อง Exception และ Limiter ก่อน
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

# 2. CORSMiddleware (ต้องอยู่เหนือ SessionMiddleware เพื่อให้หุ้ม Session ไว้)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL], # ต้องไม่มี / ปิดท้ายใน ENV
    allow_credentials=True,       # สำคัญมาก: ถ้าเป็น False จะส่ง Cookie ไม่ได้
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. SessionMiddleware อยู่ถัดมา
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="admin_session",
    same_site="none",  # บังคับ: เพื่อให้ Cookie วิ่งข้ามโดเมนได้
    https_only=True    # บังคับ: เพราะ Railway/Vercel ใช้ HTTPS
)

@app.get("/")
def health():
    return {"status": "ok"}

@app.get("/api/check-admin")
def check_admin(request: Request):
    # เช็คตรงๆ จาก session
    user = request.session.get("admin")
    if user:
        return {"authenticated": True, "user": user}
    return {"authenticated": False}

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(pdf.router)
app.include_router(analytics.router)