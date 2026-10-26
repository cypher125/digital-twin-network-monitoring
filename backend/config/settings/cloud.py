"""Cloud settings: the API on Modal, behind the dashboard on Vercel (docs/CLOUD.md).

Modal terminates HTTPS. The dashboard on Vercel forwards /api, /admin and /static to Modal, so
the browser only ever talks to the dashboard's own address and the session and CSRF cookies stay
first-party. DJANGO_ALLOWED_HOSTS and DJANGO_CSRF_TRUSTED_ORIGINS come from the Modal secret.
"""
import os
from pathlib import Path

from .prod import *  # noqa: F403

# Behind two proxies (Vercel, then Modal) the client's address arrives in a header that anyone
# calling Modal directly can write, so sign-in lockout counts failures per username, not per
# username and address (D8).
AXES_LOCKOUT_PARAMETERS = ["username"]
# axes warns that without the address an attacker can rotate cookies or User-Agents; failures
# here are counted per username whatever else changes, and the accounts' passwords are random
SILENCED_SYSTEM_CHECKS = ["axes.W006"]

# No file may stay open on the Modal volume (/app/var): a volume commit reloads it, and a reload
# fails while a file on it is open. The audit trail also goes to the console, which Modal keeps.
LOG_DIR = Path("/app/log")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING["handlers"]["audit_file"]["filename"] = str(LOG_DIR / "audit.log")  # noqa: F405

# There is no Caddy in front, so Django serves its own static files (the admin and API pages;
# the dashboard itself is on Vercel). config/urls.py adds the route when this is on.
SERVE_STATIC = True
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", "/app/static"))
