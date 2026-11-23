import asyncio
import logging
import uuid
from urllib.parse import unquote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from database import supabase
from pdf_service import BUCKET_NAME, MAX_PDF_BYTES, PdfError, index_pdf
from routes.auth import verify_admin

logger = logging.getLogger(__name__)
router = APIRouter()
index_slot = asyncio.Lock()


@router.post("/upload-pdf", dependencies=[Depends(verify_admin)])
async def upload_pdf(file: UploadFile = File(...), category: str = Form(...)):
    original_name = file.filename or ""
    if not original_name.lower().endswith(".pdf"):
        return JSONResponse(status_code=415, content={"error": "รองรับเฉพาะไฟล์ PDF"})
    category = category.strip()
    if not category:
        return JSONResponse(status_code=422, content={"error": "กรุณาระบุหมวดหมู่เอกสาร"})

    if index_slot.locked():
        return JSONResponse(
            status_code=429,
            content={"error": "กำลังเพิ่มเอกสารอีกไฟล์ กรุณารอให้เสร็จแล้วลองใหม่"},
        )

    filename = f"{uuid.uuid4()}.pdf"
    try:
        async with index_slot:
            file_bytes = await file.read(MAX_PDF_BYTES + 1)
            if len(file_bytes) > MAX_PDF_BYTES:
                return JSONResponse(status_code=413, content={"error": "รองรับไฟล์ไม่เกิน 20 MB"})
            if b"%PDF-" not in file_bytes[:1024]:
                return JSONResponse(status_code=415, content={"error": "ไฟล์นี้ไม่ใช่ PDF"})
            count = await index_pdf(file_bytes, filename, category, original_name)
    except PdfError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})
    except Exception:
        logger.exception("PDF indexing failed for %s", filename)
        return JSONResponse(
            status_code=503,
            content={"error": "ประมวลผลเอกสารไม่สำเร็จ กรุณาลองใหม่"},
        )

    return {"message": "เพิ่มเอกสารเข้าฐานความรู้แล้ว", "chunks": count}


# -----------------------
# List PDFs
# -----------------------
@router.get("/pdfs", dependencies=[Depends(verify_admin)])
def list_pdfs():
    seen = {}
    cursor = None
    while True:
        query = (
            supabase.table("documents")
            .select("id, source, original_name, category")
            .not_.is_("source", "null")
            .order("id")
            .limit(500)
        )
        if cursor is not None:
            query = query.gt("id", cursor)
        rows = query.execute().data
        if not rows:
            break
        for row in rows:
            key = row["source"]
            if key not in seen:
                seen[key] = {
                    "source": key,
                    "original_name": row.get("original_name") or key,
                    "category": row["category"],
                }
        cursor = rows[-1]["id"]

    return {"files": list(seen.values())}


# -----------------------
# View / Download PDF  (redirect ไป Supabase signed URL)
# -----------------------
@router.get("/pdfs/download/{filename}", dependencies=[Depends(verify_admin)])
def download_pdf(filename: str):

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
def delete_pdf(filename: str):

    filename = unquote(filename)

    # ลบ embeddings ออกจาก documents table
    supabase.table("documents") \
        .delete() \
        .eq("source", filename) \
        .execute()

    # ลบไฟล์จาก Supabase Storage
    supabase.storage.from_(BUCKET_NAME).remove([filename])

    return {"message": f"ลบเอกสารสำเร็จ"}
