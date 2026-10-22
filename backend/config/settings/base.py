"""Settings shared by every environment.

Values that Chapter 3 leaves open are fixed in the TWIN dictionary at the bottom
(see docs/PROJECT_PLAN.md section 3, decisions D1-D25).
"""
import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
PROJECT_DIR = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def database_from_url(url: str) -> dict:
    """Turn a postgresql:// URL (as shown in the Neon console) into a Django DATABASES entry."""
    parts = urlparse(url)
    if parts.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must start with postgresql://")
    options = dict(parse_qsl(parts.query))
    options.setdefault("sslmode", "require")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parts.path.lstrip("/")),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or 5432),
        "OPTIONS": options,
        # Keep connections open between requests and re-check them, because Neon
        # suspends idle computes and closes their connections.
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",   # Swagger UI assets served locally, not from a CDN (CSP, offline demos)
    "axes",                      # login lockout by username and address (D8)
    "apps.twin",
    "apps.accounts",
    "apps.api",
    "apps.lab",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.ActivityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",          # refuses locked-out logins before checking passwords
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25                            # hours (15 minutes)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_CALLABLE = None

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DATABASES = {"default": database_from_url(DATABASE_URL)} if DATABASE_URL else {}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Section 3.8: passwords stored with a strong, salted hash. Argon2 first; Django's
# PBKDF2 hashers remain so that any older hashes can still be verified.
PASSWORD_HASHERS = [
    "apps.accounts.hashers.TunedArgon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# D27: runtime status shared between the engine and the API, in a framework table
# (created with `manage.py createcachetable`), outside the six application tables.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "dt_runtime_cache",
        "TIMEOUT": None,
        "OPTIONS": {"MAX_ENTRIES": 1000},
    },
    # in-process cache in front of the session table, so reads do not go to Neon every request
    "sessions": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "sessions"},
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"  # D18: stored in UTC, shown in West Africa Time
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = PROJECT_DIR / "var" / "static"

# D8: a read-only dashboard may stay open for a working day (absolute limit 12 h), but
# changes need activity within the last 30 minutes (checked per request by the API, using a
# last-activity stamp that automatic polls do not update). Polls never rewrite the session.
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = False
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "sessions"
WRITE_IDLE_LIMIT_SECONDS = 30 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
    "EXCEPTION_HANDLER": "apps.api.exceptions.api_exception_handler",
    # password checks (auth/password); sign-in itself is guarded by django-axes
    "DEFAULT_THROTTLE_RATES": {"password": "10/hour"},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Digital Twin-Based Network Monitoring and Optimization System API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],  # docs for logged-in users only
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
}

LOG_DIR = PROJECT_DIR / "var" / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        # the audit trail (apps/accounts/audit.py): 5 files of 1 MB at most
        "audit_file": {"class": "logging.handlers.RotatingFileHandler", "formatter": "plain",
                       "filename": str(LOG_DIR / "audit.log"), "maxBytes": 1_000_000, "backupCount": 5,
                       "encoding": "utf-8", "delay": True},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "httpx": {"level": "WARNING"},      # not every feed request
        "httpcore": {"level": "WARNING"},
        "dt.audit": {"handlers": ["audit_file"], "level": "INFO"},  # also reaches the console via root
    },
}

# Values Chapter 3 leaves open (docs/PROJECT_PLAN.md section 3). Each one can be
# overridden with an environment variable of the same name.
TWIN = {
    # D1: health thresholds (percent) for link utilisation and device CPU
    "WARNING_THRESHOLD_PCT": float(os.environ.get("WARNING_THRESHOLD_PCT", 70)),
    "CRITICAL_THRESHOLD_PCT": float(os.environ.get("CRITICAL_THRESHOLD_PCT", 90)),
    # D2: one monitoring cycle per 60 s of network time
    "CYCLE_SECONDS": int(os.environ.get("CYCLE_SECONDS", 60)),
    # D3: forecast horizons in minutes
    "HORIZONS_MINUTES": [int(h) for h in env_list("HORIZONS_MINUTES", "5,10,15,30")],
    # D6: cycles of history needed before the first forecast
    "MIN_HISTORY_CYCLES": int(os.environ.get("MIN_HISTORY_CYCLES", 60)),
    # D19: retention (days)
    "MONITORING_RETENTION_DAYS": int(os.environ.get("MONITORING_RETENTION_DAYS", 14)),
    "PREDICTION_RETENTION_DAYS": int(os.environ.get("PREDICTION_RETENTION_DAYS", 2)),
    # D11: OSPF-style reference bandwidth for default routing costs
    "REFERENCE_BANDWIDTH_MBPS": float(os.environ.get("REFERENCE_BANDWIDTH_MBPS", 10000)),
    # NFR1/D28: how often the dashboard polls the API's `live` endpoint (seconds)
    "DASHBOARD_POLL_SECONDS": max(1, int(os.environ.get("DASHBOARD_POLL_SECONDS", 1))),
    # Data source (D9): the network emulator's read-only telemetry feed
    "EMULATOR_URL": os.environ.get("EMULATOR_URL", "http://127.0.0.1:9161"),
    "MODEL_DIR": str(PROJECT_DIR / "var" / "models"),
    # D4/D5: a link below the critical threshold is warned when the congestion classifier's
    # probability of reaching it within the horizon is at least this
    "WARNING_PROBABILITY": float(os.environ.get("WARNING_PROBABILITY", 0.5)),
}
