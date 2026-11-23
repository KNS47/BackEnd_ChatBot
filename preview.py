"""Loopback preview of the public chat using verified links and no credentials."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from municipal_info import CONTACT_URL, lookup

FRONTEND = Path(__file__).resolve().parent.parent / "FrontEnd_ChatBot"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class PreviewQuestion(BaseModel):
    message: str = Field(max_length=500)


@app.get("/health")
def health():
    return {"status": "ok", "mode": "preview"}


@app.get("/chat/history")
def history():
    return {"history": []}


@app.post("/chat")
def chat(body: PreviewQuestion):
    result = lookup(body.message)
    if result:
        answer, url = result
        return {"answer": "โหมดทดลอง\n\n" + answer + "\n\n[แหล่งข้อมูลเทศบาล](" + url + ")"}
    return {
        "answer": "โหมดทดลองตอบได้เฉพาะข้อมูลติดต่อและลิงก์บริการพื้นฐานค่ะ "
        "[ติดต่อเทศบาล](" + CONTACT_URL + ") สำหรับคำถามอื่น",
    }


@app.get("/")
@app.get("/{filename}")
def page(filename: str = "index.html"):
    if filename not in {"index.html", "chat.js", "chat.css", "config.js", "icons.svg"}:
        raise HTTPException(status_code=404, detail="Available with the live API")
    path = FRONTEND / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="FrontEnd_ChatBot checkout is required")
    return FileResponse(path)
