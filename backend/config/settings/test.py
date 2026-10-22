"""Test settings: pytest-django creates a separate test database on the Neon branch."""
from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-only-key"

# Fast hashing keeps the authentication tests quick; production uses Argon2.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Lockout is switched on only in the test that checks it.
AXES_ENABLED = False

# Tests write no audit file (the records still reach pytest's log capture).
LOGGING["handlers"]["audit_file"] = {"class": "logging.NullHandler"}  # noqa: F405
