import os

# Dummy env for imports that require Supabase/OpenRouter at module load
os.environ.setdefault("SUPABASE_URL", "http://dummy.supabase.test")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy_service_key")
os.environ.setdefault("OPENROUTER_API_KEY", "dummy_openrouter_key")
os.environ.setdefault("ESV_API_KEY", "dummy_esv_key")
