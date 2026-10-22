"""Development settings: local HTTP, debug on."""
from .base import *  # noqa: F403
from .base import SECRET_KEY, env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-do-not-use-in-production"

# The Next.js dev server runs on port 3000 and proxies /api to Django.
CSRF_TRUSTED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
