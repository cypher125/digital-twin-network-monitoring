from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.api.urls")),
]

if getattr(settings, "SERVE_STATIC", False):
    # cloud only (config/settings/cloud.py): on the laptop Caddy serves var/static
    urlpatterns.append(re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}))
