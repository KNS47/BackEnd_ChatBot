from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from typing import List
import os
import uuid

from database import supabase
from pdf_service import process_pdf_background
from routes.auth import verify_admin

router = APIRouter()

UPLOAD_DIR = "uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


# -----------------------
# Upload PDF
# -----------------------
@router.post("/pdf/upload", dependencies=[Depends(verify_admin)])
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form(...)
):

    if not file.filename.endswith(".pdf"):
        return {"error": "รองรับเฉพาะไฟล์ PDF เท่านั้น"}

    unique_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    background_tasks.add_task(
        process_pdf_background,
        file_path,
        file.filename,
        category
    )

    return {"message": "อัปโหลดสำเร็จ กำลังประมวลผล..."}


# -----------------------
# List PDFs (distinct source)
# -----------------------
@router.get("/pdf/list", dependencies=[Depends(verify_admin)])
async def list_pdfs():

    result = supabase.table("documents") \
        .select("source, category") \
        .execute()

    if not result.data:
        return {"files": []}

    seen = {}
    for row in result.data:
        seen[row["source"]] = row["category"]

    files = [
        {"source": k, "category": v}
        for k, v in seen.items()
    ]

    return {"files": files}


# -----------------------
# Delete PDF (by source)
# -----------------------
@router.delete("/pdf/{source}", dependencies=[Depends(verify_admin)])
async def delete_pdf(source: str):

    # ลบ embeddings
    supabase.table("documents") \
        .delete() \
        .eq("source", source) \
        .execute()

    return {"message": f"ลบเอกสาร {source} สำเร็จ"}