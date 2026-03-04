from pypdf import PdfReader
from database import supabase
from utils import split_text
from ai import embed_text

def process_pdf_background(file_path, filename, category):
    reader = PdfReader(file_path)
    full_text = ""

    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    chunks = split_text(full_text)

    for chunk in chunks:
        embedding = embed_text(chunk)
        supabase.table("documents").insert({
            "content": chunk,
            "embedding": embedding,
            "source": filename,
            "category": category
        }).execute()