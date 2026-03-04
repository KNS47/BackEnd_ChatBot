import os
from dotenv import load_dotenv

load_dotenv()

CACHE_TTL = 300

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
API_KEYS = os.getenv("GEMINI_API_KEYS", "").split(",")

ADMIN_USER = os.getenv("ADMIN_USERNAME")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD")

FRONTEND_URL = os.getenv("FRONTEND_URL")

SESSION_SECRET = os.getenv("SESSION_SECRET")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("Missing Supabase config")

if not API_KEYS or API_KEYS == [""]:
    raise Exception("No GEMINI_API_KEYS found")

if not SESSION_SECRET:
    raise Exception("Missing SESSION_SECRET")