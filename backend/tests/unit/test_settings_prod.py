"""Production settings (plan section 8): what the deployed system runs with."""
import importlib
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured


def load_prod(monkeypatch, **env):
    defaults = {"DJANGO_SECRET_KEY": "s" * 50, "DATABASE_URL": "postgresql://u:p@127.0.0.1:5432/db",
                "DJANGO_DEBUG": "1"}   # even if .env says debug, production ignores it
    for name, value in {**defaults, **env}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DJANGO_CSRF_TRUSTED_ORIGINS", raising=False)
    for name in ("config.settings.prod", "config.settings.base"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module("config.settings.prod")


def test_production_settings_are_locked_down(monkeypatch):
    prod = load_prod(monkeypatch)
    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE and prod.SESSION_COOKIE_HTTPONLY
    assert prod.SESSION_COOKIE_SAMESITE == "Lax"
    assert prod.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")   # Caddy terminates HTTPS
    assert prod.X_FRAME_OPTIONS == "DENY" and prod.SECURE_CONTENT_TYPE_NOSNIFF
    assert prod.PASSWORD_HASHERS[0].endswith("TunedArgon2PasswordHasher")
    assert prod.CSRF_TRUSTED_ORIGINS == ["https://localhost"]
    assert prod.DATABASES["default"]["OPTIONS"]["sslmode"] == "require"           # Neon over TLS by default
    assert "axes.middleware.AxesMiddleware" in prod.MIDDLEWARE


def test_production_refuses_to_start_without_a_secret_key(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, DJANGO_SECRET_KEY="")
