from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from typing import List
import os
import uuid
from urllib.parse import unquote

from database import supabase
from pdf_service import process_pdf_background
from routes.auth import verify_admin

router = APIRouter()

BUCKET_NAME = "pdfs"  # ชื่อ bucket ใน Supabase Storage


# -----------------------
# Upload PDF
# -----------------------
@router.post("/upload-pdf", dependencies=[Depends(verify_admin)])
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form(...)
):
    if not file.filename.endswith(".pdf"):
        return {"error": "รองรับเฉพาะไฟล์ PDF เท่านั้น"}

    original_name = file.filename                          # ชื่อที่แสดงให้ user เห็น
    unique_name = f"{uuid.uuid4()}.pdf"                    # ชื่อจริงใน storage (UUID เท่านั้น)

    file_bytes = await file.read()

    # อัปโหลดขึ้น Supabase Storage
    upload_res = supabase.storage.from_(BUCKET_NAME).upload(
        path=unique_name,
        file=file_bytes,
        file_options={"content-type": "application/pdf"}
    )

    if hasattr(upload_res, "error") and upload_res.error:
        return JSONResponse(status_code=500, content={"error": "อัปโหลดไฟล์ไม่สำเร็จ"})

    # เก็บ mapping: unique_name (storage key) <-> original_name (display)
    background_tasks.add_task(
        process_pdf_background,
        file_bytes,        # ส่ง bytes แทน path
        unique_name,       # storage key (UUID)
        category,
        original_name      # ชื่อที่แสดง — process_pdf_background ต้องรับ param นี้เพิ่ม
    )

    return {"message": "อัปโหลดสำเร็จ กำลังประมวลผล..."}


# -----------------------
# List PDFs
# -----------------------
@router.get("/pdfs", dependencies=[Depends(verify_admin)])
async def list_pdfs():

    result = supabase.table("documents") \
        .select("source, original_name, category") \
        .execute()

    if not result.data:
        return {"files": []}

    seen = {}
    for row in result.data:
        key = row["source"]
        if key not in seen:
            seen[key] = {
                "source": key,
                "original_name": row.get("original_name") or key,  # fallback
                "category": row["category"]
            }

    return {"files": list(seen.values())}


# -----------------------
# View / Download PDF  (redirect ไป Supabase signed URL)
# -----------------------
@router.get("/pdfs/download/{filename}", dependencies=[Depends(verify_admin)])
async def download_pdf(filename: str):

    filename = unquote(filename)

    # สร้าง signed URL อายุ 60 วินาที
    signed = supabase.storage.from_(BUCKET_NAME).create_signed_url(
        path=filename,
        expires_in=60
    )

    if not signed or not signed.get("signedURL"):
        return JSONResponse(status_code=404, content={"error": "ไม่พบไฟล์"})

    # Redirect ไปยัง signed URL โดยตรง
    return RedirectResponse(url=signed["signedURL"])


# -----------------------
# Delete PDF
# -----------------------
@router.delete("/pdf/{filename}", dependencies=[Depends(verify_admin)])
async def delete_pdf(filename: str):

    filename = unquote(filename)

    # ลบ embeddings ออกจาก documents table
    supabase.table("documents") \
        .delete() \
        .eq("source", filename) \
        .execute()

    # ลบไฟล์จาก Supabase Storage
    supabase.storage.from_(BUCKET_NAME).remove([filename])

    return {"message": f"ลบเอกสารสำเร็จ"}