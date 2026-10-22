"""Audit trail (plan section 8): who did what, and when.

Sign-ins (and failed attempts), sign-outs, password checks, topology changes and
imports, and every simulation request are written to the "dt.audit" logger, which
goes to var/log/audit.log as well as the console. Passwords are never logged.
"""
import logging

log = logging.getLogger("dt.audit")


def client_address(request) -> str:
    # behind Caddy the client is in X-Forwarded-For; Caddy is the only thing that can reach Waitress
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "-")


def audit(request, action: str, *, username: str | None = None, **details) -> None:
    user = getattr(request, "user", None)
    if username is None:
        username = user.username if user is not None and user.is_authenticated else "-"
    extra = " ".join(f"{key}={value}" for key, value in details.items())
    log.info("%s user=%s from=%s%s", action, username, client_address(request), f" {extra}" if extra else "")
