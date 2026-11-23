import asyncio
import logging
import os
from pathlib import Path
from threading import Lock

import pymupdf

from ai import embed_text
from database import supabase
from utils import split_text

logger = logging.getLogger(__name__)
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_PDF_CHUNKS = 400
BUCKET_NAME = os.getenv("SUPABASE_BUCKET", "pdfs").strip() or "pdfs"

# PyMuPDF does not support simultaneous calls from multiple threads.
_pdf_lock = Lock()


class PdfError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _ocr_page(page: pymupdf.Page) -> str:
    try:
        tessdata = os.getenv("TESSDATA_PREFIX") or pymupdf.get_tessdata()
    except RuntimeError as exc:
        raise PdfError("ระบบอ่านเอกสารสแกนยังไม่พร้อมใช้งาน", status_code=503) from exc
    if not tessdata or not all(
        (Path(tessdata) / f"{language}.traineddata").is_file()
        for language in ("tha", "eng")
    ):
        raise PdfError("ระบบอ่านเอกสารสแกนยังไม่พร้อมใช้งาน", status_code=503)

    # Keep 300 dpi for ordinary documents and bound the raster size for oversized pages.
    longest_edge = max(page.rect.width, page.rect.height, 1)
    dpi = max(1, min(300, int(4000 * 72 / longest_edge)))
    text_page = page.get_textpage_ocr(
        dpi=dpi, language="tha+eng", full=True, tessdata=tessdata
    )
    return page.get_text(textpage=text_page, sort=True).strip()


def extract_pages(file_bytes: bytes) -> list[tuple[int, str]]:
    with _pdf_lock:
        try:
            document = pymupdf.open(stream=file_bytes, filetype="pdf")
        except (pymupdf.FileDataError, ValueError) as exc:
            raise PdfError("เปิดไฟล์ PDF ไม่ได้ กรุณาตรวจสอบไฟล์แล้วลองใหม่") from exc

        with document:
            if document.needs_pass:
                raise PdfError("กรุณาใช้ไฟล์ PDF ที่ไม่ได้ตั้งรหัสผ่าน")
            if document.page_count > MAX_PDF_PAGES:
                raise PdfError(f"รองรับ PDF ไม่เกิน {MAX_PDF_PAGES} หน้าต่อไฟล์")

            pages = []
            for page_number, page in enumerate(document, start=1):
                text = page.get_text(sort=True).strip()
                images = page.get_image_info()
                has_scan = any(
                    (pymupdf.Rect(image["bbox"]) & page.rect).get_area() > page.rect.get_area() / 2
                    for image in images
                )
                if images and (len(text) < 40 or "\ufffd" in text or has_scan):
                    recognized = _ocr_page(page)
                    if len(recognized) > len(text) or "\ufffd" in text:
                        text = recognized or text
                if text:
                    pages.append((page_number, text))

    if not pages:
        raise PdfError("ไม่พบข้อความที่อ่านได้ กรุณาลองไฟล์ที่สแกนชัดขึ้น")
    return pages


def _store_index(file_bytes: bytes, filename: str, rows: list[dict]) -> None:
    bucket = supabase.storage.from_(BUCKET_NAME)
    bucket.upload(
        path=filename,
        file=file_bytes,
        file_options={"content-type": "application/pdf"},
    )
    try:
        # A single PostgREST insert either creates every chunk or rejects the batch.
        supabase.table("documents").insert(rows).execute()
    except Exception:
        # A failed HTTP response can still mean the database committed. Verify first
        # before removing the stored PDF; preserve the file when the outcome is unknown.
        try:
            existing = (
                supabase.table("documents").select("source")
                .eq("source", filename).limit(1).execute()
            )
            if existing.data:
                return
            bucket.remove([filename])
        except Exception:
            logger.exception("Could not reconcile PDF index for %s", filename)
        raise


async def index_pdf(file_bytes: bytes, filename: str, category: str, original_name: str) -> int:
    pages = await asyncio.to_thread(extract_pages, file_bytes)
    chunks = [(page, chunk) for page, text in pages for chunk in split_text(text)]
    if len(chunks) > MAX_PDF_CHUNKS:
        raise PdfError("ไฟล์มีข้อความมากเกินไป กรุณาแบ่งเอกสารเป็นหลายไฟล์")
    rows = []
    for chunk_index, (page_number, chunk) in enumerate(chunks):
        rows.append({
            "content": chunk,
            "embedding": await embed_text(chunk),
            "source": filename,
            "original_name": original_name,
            "category": category,
            "chunk_index": chunk_index,
            "page_number": page_number,
        })
    await asyncio.to_thread(_store_index, file_bytes, filename, rows)
    return len(rows)
