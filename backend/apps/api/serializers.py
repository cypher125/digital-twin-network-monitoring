"""Input validation for everything the API accepts (section 3.8: input validation)."""
from django.db.models import Q
from rest_framework import serializers

from apps.twin.models import (
    ElementStatus,
    NetworkDevice,
    NetworkLink,
    SimulationResult,
    SimulationScenario,
)
from digital_twin.runtime.persistence import links_in_service

RETIRED = ElementStatus.DECOMMISSIONED


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NetworkDevice
        fields = ["device_id", "name", "device_type", "ip_address", "location", "status", "configuration"]
        read_only_fields = ["device_id"]

    def validate_configuration(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Configuration must be an object.")
        position = value.get("position")
        if position is not None and (not isinstance(position, list | tuple) or len(position) != 2):
            raise serializers.ValidationError("position must be [x, y].")
        return value

    def validate(self, attrs):
        """A device can be retired only when none of its links is still in service.

        In service as everywhere else (links_in_service): a link whose other end is already
        retired has left the network, so the dashboard does not show it and it does not count."""
        if attrs.get("status") == RETIRED and self.instance is not None:
            links = (links_in_service().filter(Q(source_device=self.instance) | Q(dest_device=self.instance))
                     .select_related("source_device", "dest_device").order_by("link_id"))
            in_service = list(links)
            if in_service:
                one = len(in_service) == 1
                names = ", ".join(str(lk) for lk in in_service[:3])
                more = f" and {len(in_service) - 3} more" if len(in_service) > 3 else ""
                raise serializers.ValidationError({"status": (
                    f"This device still has {len(in_service)} link{'' if one else 's'} in service "
                    f"({names}{more}). Set {'it' if one else 'each of them'} to Decommissioned first, "
                    "then retire the device.")})
        return attrs


class LinkSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = NetworkLink
        fields = ["link_id", "source_device", "dest_device", "capacity_mbps", "status", "routing_cost", "label"]
        read_only_fields = ["link_id", "label"]

    def get_label(self, obj) -> str:
        return f"{obj.source_device.name} <-> {obj.dest_device.name}"

    def validate_capacity_mbps(self, value):
        if value <= 0:
            raise serializers.ValidationError("Capacity must be a positive number of Mbps.")
        return value

    def validate_routing_cost(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Routing cost must be positive.")
        return value

    def validate(self, attrs):
        source = attrs.get("source_device", getattr(self.instance, "source_device", None))
        dest = attrs.get("dest_device", getattr(self.instance, "dest_device", None))
        if source is not None and source == dest:
            raise serializers.ValidationError("A link must connect two different devices.")
        status = attrs.get("status", getattr(self.instance, "status", ElementStatus.UNKNOWN))
        retired = [d.name for d in (source, dest) if d is not None and d.status == RETIRED]
        if retired and status != RETIRED:
            which = f"{retired[0]} is" if len(retired) == 1 else f"{retired[0]} and {retired[1]} are"
            raise serializers.ValidationError({"status": (
                f"{which} decommissioned, so this link can only be saved as Decommissioned. "
                "Bring the device back into service first if the link is still in use.")})
        return attrs


class ScenarioSerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="created_by.username", read_only=True)
    runs = serializers.IntegerField(source="results.count", read_only=True)

    class Meta:
        model = SimulationScenario
        fields = ["scenario_id", "scenario_name", "scenario_type", "parameters", "created_by", "created_at", "runs"]
        read_only_fields = ["scenario_id", "created_by", "created_at", "runs"]

    def validate_scenario_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Please give the scenario a name.")
        return value

    def validate_parameters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Parameters must be an object.")
        if len(str(value)) > 10_000:
            raise serializers.ValidationError("Parameters are too large.")
        return value


class RunRequestSerializer(serializers.Serializer):
    basis = serializers.ChoiceField(choices=["current", "forecast"], default="current")
    horizon_minutes = serializers.IntegerField(required=False, default=30)

    def validate_horizon_minutes(self, value):
        from django.conf import settings
        if value not in settings.TWIN["HORIZONS_MINUTES"]:
            raise serializers.ValidationError(f"Horizon must be one of {settings.TWIN['HORIZONS_MINUTES']}.")
        return value


class ResultSerializer(serializers.ModelSerializer):
    scenario_name = serializers.CharField(source="scenario.scenario_name", read_only=True)
    scenario_type = serializers.CharField(source="scenario.scenario_type", read_only=True)
    run_by = serializers.CharField(source="run_by.username", read_only=True, default=None)

    class Meta:
        model = SimulationResult
        fields = ["result_id", "scenario", "scenario_name", "scenario_type", "status", "requested_at", "executed_at",
                  "run_by", "predicted_utilisation", "bottleneck_links", "result_summary"]
        read_only_fields = fields


class ResultListSerializer(serializers.ModelSerializer):
    """A light version for lists: no per-link data."""

    scenario_name = serializers.CharField(source="scenario.scenario_name", read_only=True)
    scenario_type = serializers.CharField(source="scenario.scenario_type", read_only=True)
    run_by = serializers.CharField(source="run_by.username", read_only=True, default=None)
    summary = serializers.SerializerMethodField()

    class Meta:
        model = SimulationResult
        fields = ["result_id", "scenario", "scenario_name", "scenario_type", "status", "requested_at", "executed_at",
                  "run_by", "summary"]
        read_only_fields = fields

    def get_summary(self, obj) -> str:
        summary = obj.result_summary or {}
        return summary.get("summary") or summary.get("error") or ""
