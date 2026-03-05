from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi.responses import RedirectResponse
import uuid

from database import supabase
from routes.auth import verify_admin

router = APIRouter()

BUCKET = "psfs"


# -----------------------
# Upload PDF
# -----------------------
@router.post("/upload-pdf", dependencies=[Depends(verify_admin)])
async def upload_pdf(
    file: UploadFile = File(...),
    category: str = Form(...)
):

    if not file.filename.endswith(".pdf"):
        return {"error": "รองรับเฉพาะ PDF"}

    unique_name = f"{uuid.uuid4()}_{file.filename}"

    file_bytes = await file.read()

    # upload storage
    supabase.storage.from_(BUCKET).upload(
        unique_name,
        file_bytes,
        {"content-type": "application/pdf"}
    )

    # save metadata
    supabase.table("documents").insert({
        "source": unique_name,
        "category": category
    }).execute()

    return {"message": "อัปโหลดสำเร็จ"}


# -----------------------
# List PDFs
# -----------------------
@router.get("/pdfs", dependencies=[Depends(verify_admin)])
async def list_pdfs():

    data = supabase.table("documents").select("*").execute()

    return {"files": data.data}


# -----------------------
# View PDF
# -----------------------
@router.get("/pdfs/{filename}", dependencies=[Depends(verify_admin)])
async def view_pdf(filename: str):

    url = supabase.storage.from_(BUCKET).get_public_url(filename)

    return RedirectResponse(url)


# -----------------------
# Download PDF
# -----------------------
@router.get("/pdfs/download/{filename}", dependencies=[Depends(verify_admin)])
async def download_pdf(filename: str):

    url = supabase.storage.from_(BUCKET).get_public_url(filename)

    return RedirectResponse(url)


# -----------------------
# Delete PDF
# -----------------------
@router.delete("/pdf/{source}", dependencies=[Depends(verify_admin)])
async def delete_pdf(source: str):

    # delete storage
    supabase.storage.from_(BUCKET).remove([source])

    # delete db
    supabase.table("documents") \
        .delete() \
        .eq("source", source) \
        .execute()

    return {"message": "ลบสำเร็จ"}