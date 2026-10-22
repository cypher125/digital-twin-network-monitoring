"""The six application tables of Figure 3.3 / Table 3.2.

Model and field names follow Chapter 3 exactly. Fields marked "non-principal"
are additions allowed because Table 3.2 lists only principal fields; each one
is recorded in docs/AS_BUILT_NOTES.md (plan decision D13).

All foreign keys use PROTECT: history and the audit trail are never deleted by
accident. Devices and links are retired by setting status to "decommissioned".
"""
from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Greatest, Least


class ElementStatus(models.TextChoices):
    UP = "up", "Up"
    DOWN = "down", "Down"
    UNKNOWN = "unknown", "Unknown"
    DECOMMISSIONED = "decommissioned", "Decommissioned"


class DeviceType(models.TextChoices):
    ROUTER = "router", "Router"
    SWITCH = "switch", "Switch"
    FIREWALL = "firewall", "Firewall"
    SERVER = "server", "Server"
    ACCESS_POINT = "access_point", "Access point"
    WAN_GATEWAY = "wan_gateway", "WAN gateway (ISP)"


class ScenarioType(models.TextChoices):
    TRAFFIC_INCREASE = "traffic_increase", "Traffic increase"
    LINK_FAILURE = "link_failure", "Link failure"
    DEVICE_FAILURE = "device_failure", "Device failure"
    ROUTING_CHANGE = "routing_change", "Routing change"
    REROUTE_TRAFFIC = "reroute_traffic", "Reroute traffic"
    CAPACITY_CHANGE = "capacity_change", "Capacity change"
    ACCESS_CONTROL_RULE = "access_control_rule", "Access control rule"
    QOS_POLICY = "qos_policy", "QoS policy"
    ADD_LINK = "add_link", "Add link"


class RunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class NetworkDevice(models.Model):
    """One device in the network topology: a node of the network graph (D1 Topology Store)."""

    device_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    device_type = models.CharField(max_length=20, choices=DeviceType.choices)
    ip_address = models.GenericIPAddressField(unique=True, null=True, blank=True)
    location = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20, choices=ElementStatus.choices, default=ElementStatus.UNKNOWN
    )
    # Non-principal: role, zone, vendor/model, interface-to-link map, diagram
    # position, ACL and QoS settings (FR1 "configuration for nodes").
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "network_device"
        ordering = ["device_id"]

    def __str__(self) -> str:
        return self.name


class NetworkLink(models.Model):
    """One connection between two devices: an edge of the network graph (D1 Topology Store)."""

    link_id = models.BigAutoField(primary_key=True)
    source_device = models.ForeignKey(
        NetworkDevice, on_delete=models.PROTECT, related_name="links_as_source"
    )
    dest_device = models.ForeignKey(
        NetworkDevice, on_delete=models.PROTECT, related_name="links_as_dest"
    )
    capacity_mbps = models.FloatField()
    status = models.CharField(
        max_length=20, choices=ElementStatus.choices, default=ElementStatus.UNKNOWN
    )
    # Non-principal: OSPF-style routing cost; empty means 10,000 / capacity_mbps (D11).
    routing_cost = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "network_link"
        ordering = ["link_id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity_mbps__gt=0), name="networklink_capacity_positive"
            ),
            models.CheckConstraint(
                condition=~Q(source_device=F("dest_device")),
                name="networklink_distinct_endpoints",
            ),
            models.UniqueConstraint(
                Least("source_device", "dest_device"),
                Greatest("source_device", "dest_device"),
                name="networklink_unique_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_device} <-> {self.dest_device}"


class MonitoringRecord(models.Model):
    """The state of one device OR one link at one point in time (D2 Monitoring Records).

    Exactly one of device / link is set. Link rows carry traffic_in, traffic_out
    and utilisation_pct; device rows carry cpu_util and interface totals.
    On a link, traffic_out is source -> destination and traffic_in is
    destination -> source, all in Mbps.
    """

    record_id = models.BigAutoField(primary_key=True)
    # db_index=False: the partial unique indexes below already lead with these columns.
    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="monitoring_records",
        db_index=False,
    )
    link = models.ForeignKey(
        NetworkLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="monitoring_records",
        db_index=False,
    )
    timestamp = models.DateTimeField()
    traffic_in = models.FloatField(null=True, blank=True)
    traffic_out = models.FloatField(null=True, blank=True)
    utilisation_pct = models.FloatField(null=True, blank=True)
    error_count = models.PositiveIntegerField(null=True, blank=True)
    cpu_util = models.FloatField(null=True, blank=True)
    # Non-principal: status at that time (availability history); empty if not reported.
    status = models.CharField(max_length=20, choices=ElementStatus.choices, blank=True, default="")
    # Non-principal: when the network adapter received the data (NFR1 measurement).
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "monitoring_record"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(device__isnull=False, link__isnull=True)
                    | Q(device__isnull=True, link__isnull=False)
                ),
                name="monitoringrecord_device_xor_link",
            ),
            models.UniqueConstraint(
                fields=["link", "timestamp"],
                condition=Q(link__isnull=False),
                name="monitoringrecord_unique_link_ts",
            ),
            models.UniqueConstraint(
                fields=["device", "timestamp"],
                condition=Q(device__isnull=False),
                name="monitoringrecord_unique_device_ts",
            ),
            models.CheckConstraint(
                condition=Q(utilisation_pct__isnull=True)
                | Q(utilisation_pct__gte=0, utilisation_pct__lte=100),
                name="monitoringrecord_utilisation_range",
            ),
            models.CheckConstraint(
                condition=Q(cpu_util__isnull=True) | Q(cpu_util__gte=0, cpu_util__lte=100),
                name="monitoringrecord_cpu_range",
            ),
        ]
        indexes = [BrinIndex(fields=["timestamp"], name="monitoringrecord_ts_brin")]

    def __str__(self) -> str:
        subject = f"link {self.link_id}" if self.link_id else f"device {self.device_id}"
        return f"{subject} at {self.timestamp:%Y-%m-%d %H:%M}"


class Prediction(models.Model):
    """One forecast for one link at one horizon, produced every monitoring cycle (D3 Predictions)."""

    prediction_id = models.BigAutoField(primary_key=True)
    link = models.ForeignKey(
        NetworkLink, on_delete=models.PROTECT, related_name="predictions", db_index=False
    )
    generated_at = models.DateTimeField()
    horizon_minutes = models.PositiveSmallIntegerField()
    predicted_utilisation = models.FloatField()
    confidence_score = models.FloatField()
    is_warning = models.BooleanField(default=False)
    # Non-principal: which trained model produced this forecast.
    model_version = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "prediction"
        constraints = [
            models.UniqueConstraint(
                fields=["link", "generated_at", "horizon_minutes"],
                name="prediction_unique_link_time_horizon",
            ),
            models.CheckConstraint(
                condition=Q(confidence_score__gte=0, confidence_score__lte=1),
                name="prediction_confidence_range",
            ),
            models.CheckConstraint(
                condition=Q(horizon_minutes__gt=0), name="prediction_horizon_positive"
            ),
        ]
        indexes = [
            BrinIndex(fields=["generated_at"], name="prediction_generated_brin"),
            models.Index(
                fields=["-generated_at"],
                condition=Q(is_warning=True),
                name="prediction_warning_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"link {self.link_id} +{self.horizon_minutes} min: {self.predicted_utilisation:.1f} %"


class SimulationScenario(models.Model):
    """A hypothetical scenario defined by an administrator (D4 Scenarios and Results)."""

    scenario_id = models.BigAutoField(primary_key=True)
    # Column named exactly "created_by", as in Figure 3.3. Points to Django's built-in user table.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="simulation_scenarios",
        db_column="created_by",
    )
    scenario_name = models.CharField(max_length=120)
    scenario_type = models.CharField(max_length=30, choices=ScenarioType.choices)
    parameters = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "simulation_scenario"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.scenario_name


class SimulationResult(models.Model):
    """One execution of one scenario by the simulation engine (D4 Scenarios and Results)."""

    result_id = models.BigAutoField(primary_key=True)
    scenario = models.ForeignKey(
        SimulationScenario, on_delete=models.PROTECT, related_name="results"
    )
    executed_at = models.DateTimeField(null=True, blank=True)
    # {link_id: utilisation %} for every link after the change
    predicted_utilisation = models.JSONField(default=dict, blank=True)
    # links at or above the critical threshold after the change
    bottleneck_links = models.JSONField(default=list, blank=True)
    # plain-language summary plus the stored baseline used for comparison
    result_summary = models.JSONField(default=dict, blank=True)
    # Non-principal: run queue status, who asked for the run, and when.
    status = models.CharField(max_length=20, choices=RunStatus.choices, default=RunStatus.QUEUED)
    run_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="simulation_runs",
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "simulation_result"
        ordering = ["-requested_at"]
        indexes = [
            models.Index(
                fields=["requested_at"],
                condition=Q(status="queued"),
                name="simulationresult_queue_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"result {self.result_id} of scenario {self.scenario_id} ({self.status})"
