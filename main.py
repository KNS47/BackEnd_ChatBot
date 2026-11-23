from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from ai import gemini_lifespan
from config import COOKIE_SAMESITE, COOKIE_SECURE, FRONTEND_ORIGINS, SESSION_SECRET
from middleware import limiter, rate_limit_handler
from routes import analytics, auth, chat, pdf

app = FastAPI(lifespan=gemini_lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="admin_session",
    max_age=auth.ADMIN_SESSION_MAX_AGE,
    same_site=COOKIE_SAMESITE,
    https_only=COOKIE_SECURE,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/check-admin")
def check_admin(request: Request):
    user = auth.current_admin(request)
    return {"authenticated": True, "user": user} if user else {"authenticated": False}

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(pdf.router)
app.include_router(analytics.router)

web = Path(__file__).with_name("web")
if (web / "index.html").is_file():
    app.mount("/", StaticFiles(directory=web, html=True), name="frontend")
else:
    @app.get("/")
    def root_health():
        return {"status": "ok"}
