"""Admin pages for the six tables: VIEW ONLY.

Monitoring records, predictions and simulation results are evidence, so nobody
can add, edit or delete them through the admin site. Topology changes go through
the validated import and API; the admin is used for users and roles only.
"""
from django.contrib import admin

from .models import (
    MonitoringRecord,
    NetworkDevice,
    NetworkLink,
    Prediction,
    SimulationResult,
    SimulationScenario,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NetworkDevice)
class NetworkDeviceAdmin(ReadOnlyAdmin):
    list_display = ("device_id", "name", "device_type", "ip_address", "location", "status")
    list_filter = ("device_type", "status", "location")
    search_fields = ("name", "ip_address", "location")


@admin.register(NetworkLink)
class NetworkLinkAdmin(ReadOnlyAdmin):
    list_display = ("link_id", "source_device", "dest_device", "capacity_mbps", "status")
    list_filter = ("status",)
    list_select_related = ("source_device", "dest_device")


@admin.register(MonitoringRecord)
class MonitoringRecordAdmin(ReadOnlyAdmin):
    list_display = ("record_id", "timestamp", "device", "link", "utilisation_pct", "cpu_util", "status")
    list_select_related = ("device", "link")
    date_hierarchy = "timestamp"


@admin.register(Prediction)
class PredictionAdmin(ReadOnlyAdmin):
    list_display = (
        "prediction_id", "link", "generated_at", "horizon_minutes",
        "predicted_utilisation", "confidence_score", "is_warning",
    )
    list_filter = ("is_warning", "horizon_minutes")


@admin.register(SimulationScenario)
class SimulationScenarioAdmin(ReadOnlyAdmin):
    list_display = ("scenario_id", "scenario_name", "scenario_type", "created_by", "created_at")
    list_filter = ("scenario_type",)


@admin.register(SimulationResult)
class SimulationResultAdmin(ReadOnlyAdmin):
    list_display = ("result_id", "scenario", "status", "executed_at", "run_by")
    list_filter = ("status",)
