import re

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

            for i in range(0, len(para), chunk_size):
                chunks.append(para[i:i+chunk_size].strip())
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