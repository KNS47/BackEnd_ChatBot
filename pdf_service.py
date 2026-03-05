import io
import fitz  # PyMuPDF
import pdfplumber
from database import supabase
from utils import split_text
from ai import embed_text


def extract_text_from_bytes(file_bytes: bytes) -> str:
    # ลอง PyMuPDF ก่อน (เร็วกว่า)
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()

    # ถ้าได้ข้อความน้อยเกินไป (เช่น PDF มีตารางหรือ layout ซับซ้อน) ให้ลอง pdfplumber
    if len(text.strip()) < 100:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            text = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )

    return text


def process_pdf_background(
    file_bytes: bytes,
    filename: str,       # UUID key ใน Supabase Storage
    category: str,
    original_name: str   # ชื่อไฟล์จริงที่แสดงให้ user เห็น
):
    full_text = extract_text_from_bytes(file_bytes)

    if not full_text.strip():
        print(f"[pdf_service] ไม่พบข้อความใน {original_name}")
        return

    chunks = split_text(full_text)

    for chunk in chunks:
        embedding = embed_text(chunk)
        supabase.table("documents").insert({
            "content": chunk,
            "embedding": embedding,
            "source": filename,           # UUID — ใช้อ้างอิง storage
            "original_name": original_name,  # ชื่อที่แสดง
            "category": category
        }).execute()

    print(f"[pdf_service] ประมวลผล {original_name} สำเร็จ ({len(chunks)} chunks)")