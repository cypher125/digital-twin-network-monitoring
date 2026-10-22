"""Authentication (section 3.8; use case "Authenticate (log in)", Figure 3.5).

The dashboard is a static build, so it fetches a CSRF token from `auth/csrf` before
logging in. Login is CSRF-protected (DRF skips CSRF for anonymous requests, so
this view enforces it), locked out after repeated failures (django-axes), and
starts the activity stamp used by the write rule (D8).
"""
import time

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.audit import audit
from apps.accounts.middleware import idle_limit
from apps.accounts.roles import role_of


def describe_user(request) -> dict:
    user = request.user
    last = request.session.get("last_activity")
    unlocked = not request.session.get("write_locked") and last is not None and time.time() - last <= idle_limit()
    return {
        "username": user.username,
        "full_name": user.get_full_name(),
        "role": role_of(user),
        "is_staff": user.is_staff,
        "write_allowed": role_of(user) == "senior" and unlocked,
    }


def mark_active(request) -> None:
    """The password was just checked: changes are allowed again for the next 30 minutes."""
    request.session["last_activity"] = time.time()
    request.session["write_locked"] = False


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Sets the CSRF cookie and returns the token (the static dashboard calls this first)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        form = LoginSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        user = authenticate(request, username=form.validated_data["username"],
                            password=form.validated_data["password"])
        if user is None:
            locked = getattr(request, "axes_locked_out", False)
            audit(request, "login_failed", username=form.validated_data["username"][:150], locked=locked)
            message = ("Too many failed attempts. Please wait 15 minutes and try again." if locked
                       else "Incorrect username or password.")
            return Response({"detail": message}, status=status.HTTP_403_FORBIDDEN if locked
                            else status.HTTP_400_BAD_REQUEST)
        if role_of(user) == "none":
            audit(request, "login_refused", username=user.username, reason="no role")
            return Response({"detail": "This account has no administrator role."}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        mark_active(request)
        audit(request, "login", role=role_of(user))
        # Django rotates the CSRF token at login; the dashboard must use the new one.
        return Response({"user": describe_user(request), "csrfToken": get_token(request)})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        audit(request, "logout")
        logout(request)
        return Response({"detail": "Logged out."})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(describe_user(request))


class PasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False, allow_blank=True, required=False, default="")


class PasswordView(APIView):
    """Change your own password, or confirm it (re-authenticate) to make changes again (D8).

    Throttled, because django-axes only guards the login form: without a limit, a stolen
    session could be used to guess the password here."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password"

    def post(self, request):
        form = PasswordSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(form.validated_data["current_password"]):
            audit(request, "password_check_failed")
            return Response({"detail": "Your current password is not correct."}, status=status.HTTP_400_BAD_REQUEST)
        new = form.validated_data["new_password"]
        if new:
            try:
                validate_password(new, user)
            except ValidationError as exc:
                return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
            user.set_password(new)
            user.save()
            update_session_auth_hash(request, user)
        mark_active(request)
        audit(request, "password_changed" if new else "password_confirmed")
        return Response({"detail": "Password changed." if new else "Confirmed.", "user": describe_user(request)})
