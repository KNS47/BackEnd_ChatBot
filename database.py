from supabase import ClientOptions, create_client

from config import SUPABASE_KEY, SUPABASE_URL

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
    options=ClientOptions(postgrest_client_timeout=8, storage_client_timeout=30),
)
