"""Authorisation rules (section 3.8, plan decisions D7 and D8).

* Everyone must be logged in.
* Junior Administrators may only read (GET, HEAD, OPTIONS).
* Senior Administrators may also change things, provided they were active (a
  non-automatic request) within the last 30 minutes; otherwise the dashboard asks
  them to confirm their password first.
"""
import time

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.middleware import idle_limit
from apps.accounts.roles import is_senior


class RecentActivityRequired(PermissionDenied):
    """403 with code "reauthenticate": the dashboard then asks for the password (auth/password)."""

    default_detail = "You have been inactive for a while. Please confirm your password to make changes."
    default_code = "reauthenticate"


def check_recent_activity(request) -> None:
    previous = getattr(request, "previous_activity", None)
    if request.session.get("write_locked") or previous is None or time.time() - previous > idle_limit():
        raise RecentActivityRequired()


class IsSeniorOrReadOnly(BasePermission):
    message = "Only a Senior Administrator can make changes."

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        if not is_senior(request.user):
            return False
        check_recent_activity(request)
        return True


class IsSenior(BasePermission):
    message = "Only a Senior Administrator can see this."

    def has_permission(self, request, view) -> bool:
        if not is_senior(request.user):
            return False
        if request.method not in SAFE_METHODS:
            check_recent_activity(request)
        return True
