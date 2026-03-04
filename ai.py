import random
import google.generativeai as genai
from config import API_KEYS

current_index = random.randint(0, len(API_KEYS) - 1)

def use_key(index):
    genai.configure(api_key=API_KEYS[index].strip())

GENERATION_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash"
]

def embed_text(text):
    global current_index
    last_error = None

    for i in range(len(API_KEYS)):
        idx = (current_index + i) % len(API_KEYS)
        try:
            use_key(idx)
            result = genai.embed_content(
                model="gemini-embedding-001",
                content=text
            )
            current_index = idx
            return result["embedding"]
        except Exception as e:
            last_error = e

    raise last_error


def generate_answer(prompt):
    global current_index
    last_error = None

    for k in range(len(API_KEYS)):
        key_index = (current_index + k) % len(API_KEYS)

        try:
            use_key(key_index)

            for model_name in GENERATION_MODELS:
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)

                    current_index = key_index
                    return response.text
                except Exception as model_error:
                    last_error = model_error

        except Exception as key_error:
            last_error = key_error

    raise last_error