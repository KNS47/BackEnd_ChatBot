import re

URL_PATTERN = re.compile(r'https?://\S+')

def _split_long_para(para: str, chunk_size: int) -> list:
    """ตัด paragraph ยาวโดยไม่ตัดกลาง URL"""
    result = []
    current = ""

    # แยก tokens: URL เป็น 1 token, คำอื่นแยกด้วยช่องว่าง
    tokens = []
    last = 0
    for m in URL_PATTERN.finditer(para):
        if m.start() > last:
            tokens.extend(para[last:m.start()].split())
        tokens.append(m.group())  # URL ทั้งก้อนเป็น 1 token
        last = m.end()
    if last < len(para):
        tokens.extend(para[last:].split())

    for token in tokens:
        # URL ยาวมากกว่า chunk_size → เก็บเป็น chunk เดี่ยว
        if len(token) > chunk_size:
            if current:
                result.append(current.strip())
                current = ""
            result.append(token)
            continue

        if len(current) + len(token) + 1 > chunk_size:
            result.append(current.strip())
            current = token
        else:
            current = (current + " " + token).strip() if current else token

    if current:
        result.append(current.strip())

    return result


def split_text(text, chunk_size=1000, overlap=200):
    text = text.replace("\r", "")
    text = re.sub(r'\n{2,}', '\n\n', text)

    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(para) > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # ใช้ _split_long_para แทนการตัดดิบๆ เพื่อไม่ให้ URL ขาด
            for sub in _split_long_para(para, chunk_size):
                chunks.append(sub)
            continue

        if len(current_chunk) + len(para) + 2 > chunk_size:
            chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk.strip())

    final_chunks = []

    for i in range(len(chunks)):
        if i == 0:
            final_chunks.append(chunks[i])
        else:
            prev = final_chunks[-1]
            overlap_text = prev[-overlap:]
            combined = overlap_text + "\n" + chunks[i]
            final_chunks.append(combined.strip())

    return final_chunks