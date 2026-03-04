from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from config import SESSION_SECRET
from middleware import limiter, rate_limit_handler
from slowapi.errors import RateLimitExceeded

from routes import auth, chat, pdf, analytics

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["FRONTEND_URL"],  # เปลี่ยนเป็น URL ของ frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(pdf.router)
app.include_router(analytics.router)