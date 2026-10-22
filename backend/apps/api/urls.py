"""REST API routes (plan section 7.8). All need a login except auth/csrf and auth/login."""
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from .views import alerts, auth, elements, live, simulation, system, trends

router = DefaultRouter(trailing_slash=False)
router.register("devices", elements.DeviceViewSet, basename="device")
router.register("links", elements.LinkViewSet, basename="link")
router.register("scenarios", simulation.ScenarioViewSet, basename="scenario")
router.register("results", simulation.ResultViewSet, basename="result")

urlpatterns = [
    path("auth/csrf", auth.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login", auth.LoginView.as_view(), name="auth-login"),
    path("auth/logout", auth.LogoutView.as_view(), name="auth-logout"),
    path("auth/me", auth.MeView.as_view(), name="auth-me"),
    path("auth/password", auth.PasswordView.as_view(), name="auth-password"),
    path("live", live.LiveView.as_view(), name="live"),
    path("topology", live.TopologyView.as_view(), name="topology"),
    path("topology/import", system.TopologyImportView.as_view(), name="topology-import"),
    path("alerts/active", alerts.ActiveAlertsView.as_view(), name="alerts-active"),
    path("alerts/history", alerts.AlertHistoryView.as_view(), name="alerts-history"),
    path("scenario-types", simulation.ScenarioTypesView.as_view(), name="scenario-types"),
    path("trends/links", trends.LinkTrendsView.as_view(), name="trends-links"),
    path("trends/network", trends.NetworkTrendView.as_view(), name="trends-network"),
    path("trends/heatmap", trends.HeatmapView.as_view(), name="trends-heatmap"),
    path("trends/capacity", trends.CapacityView.as_view(), name="trends-capacity"),
    path("trends/export.csv", trends.TrendsExportView.as_view(), name="trends-export"),
    path("system/status", system.StatusView.as_view(), name="system-status"),
    path("settings", system.SettingsView.as_view(), name="settings"),
    path("users", system.UsersView.as_view(), name="users"),
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("", include(router.urls)),
]
