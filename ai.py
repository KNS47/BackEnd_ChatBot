import random
import asyncio
import logging
import google.generativeai as genai
from config import API_KEYS

logger = logging.getLogger(__name__)

current_index = random.randint(0, len(API_KEYS) - 1)

GENERATION_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]


def _use_key(index: int) -> None:
    genai.configure(api_key=API_KEYS[index].strip())


# ---------------------------------------------------------------------------
# embed_text — async (run sync SDK in thread pool ไม่บล็อก event loop)
# ---------------------------------------------------------------------------
async def embed_text(text: str) -> list:
    global current_index
    last_error = None

    for i in range(len(API_KEYS)):
        idx = (current_index + i) % len(API_KEYS)
        try:
            def _sync_embed():
                _use_key(idx)
                result = genai.embed_content(
                    model="gemini-embedding-001",
                    content=text,
                )
                return result["embedding"]

            embedding = await asyncio.get_event_loop().run_in_executor(None, _sync_embed)
            current_index = idx
            return embedding

        except Exception as e:
            last_error = e
            logger.warning(f"embed_text key[{idx}] error: {e}")

    raise last_error


# ---------------------------------------------------------------------------
# generate_answer — async (run sync SDK in thread pool ไม่บล็อก event loop)
# ---------------------------------------------------------------------------
async def generate_answer(prompt: str) -> str:
    global current_index
    last_error = None

    # สลับคีย์ก่อนเป็นอันดับแรก
    for k in range(len(API_KEYS)):
        key_index = (current_index + k) % len(API_KEYS)
        
        # ลองใช้โมเดลที่ต้องการ (เช่น lite)
        for model_name in GENERATION_MODELS:
            try:
                def _sync_generate(ki=key_index, mn=model_name):
                    _use_key(ki)
                    model = genai.GenerativeModel(mn)
                    response = model.generate_content(prompt)
                    return response.text

                text = await asyncio.get_event_loop().run_in_executor(None, _sync_generate)
                current_index = key_index # บันทึกคีย์ที่ใช้งานได้ล่าสุด
                return text
            except Exception as e:
                last_error = e
                logger.warning(f"Key[{key_index}] Model[{model_name}] failed: {e}")
                # ถ้าเป็น Error 429 (Quota) ให้หยุดลองโมเดลอื่นในคีย์นี้ แล้วไปคีย์ถัดไปทันที
                if "429" in str(e):
                    break 
    raise last_error