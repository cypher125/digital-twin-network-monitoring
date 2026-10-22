"""User-activity tracking for the write rule of plan decision D8.

A read-only dashboard may stay open for a working day, but changes need activity
within the last 30 minutes. Automatic polls (X-Poll header) are not activity, so a
dashboard left open does not keep write permission alive. The stamp from BEFORE
this request is kept on the request, so a write cannot authorise itself.

When someone comes back after a longer absence, reading pages is fine, but changes
stay locked until the password is confirmed (auth/password). Otherwise anyone who
found the screen unattended could click one page and then make changes.
"""
import time

from django.conf import settings


def idle_limit() -> float:
    return float(getattr(settings, "WRITE_IDLE_LIMIT_SECONDS", 30 * 60))


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.previous_activity = None
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            session = request.session
            previous = session.get("last_activity")
            request.previous_activity = previous
            if request.headers.get("X-Poll") != "1":
                now = time.time()
                if previous is None or now - previous > idle_limit():
                    session["write_locked"] = True
                session["last_activity"] = now
        return self.get_response(request)
