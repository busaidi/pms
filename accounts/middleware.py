from django.shortcuts import redirect
from django.conf import settings
from django.utils import translation

from .models import AuditLog
from .audit import begin, end


class PreferredLanguageMiddleware:
    """Keep authenticated requests aligned with the saved profile preference."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile = getattr(request.user, "pms_profile", None)
            language = getattr(profile, "preferred_language", "")
            if language in dict(settings.LANGUAGES):
                translation.activate(language)
                request.LANGUAGE_CODE = language
        return self.get_response(request)


class TwoFactorMiddleware:
    allowed_prefixes = ("/account/two-factor/challenge/", "/logout/", "/static/", "/health/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile = getattr(request.user, "pms_profile", None)
            if profile and profile.two_factor_enabled and not request.session.get("two_factor_verified"):
                if not request.path.startswith(self.allowed_prefixes):
                    request.session["two_factor_next"] = request.get_full_path()
                    return redirect("two_factor_challenge")
        return self.get_response(request)


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        ip_address = forwarded or request.META.get("REMOTE_ADDR")
        token = begin(request.user if request.user.is_authenticated else None, ip_address)
        try:
            response = self.get_response(request)
            if request.user.is_authenticated and request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 400:
                if not request.path.startswith(("/login/", "/account/two-factor/challenge/")):
                    AuditLog.objects.create(
                        actor=request.user,
                        action=f"http.{request.method.lower()}",
                        target_type="request",
                        target_id=request.path[:80],
                        summary=f"{request.method} {request.path}"[:255],
                        changes={"status": response.status_code},
                        ip_address=ip_address,
                    )
            return response
        finally:
            end(token)
