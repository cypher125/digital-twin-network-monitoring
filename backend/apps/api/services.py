"""Shared helpers for the API (Figure 3.4 process 6.0 reads D1-D4).

Designed for a remote database (Neon, D24): few queries per request, and payloads
cached in this process by the engine's state version (D28), so many dashboards
polling at once cost one database read per cycle.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.forms.models import model_to_dict

from apps.twin.models import ElementStatus, MonitoringRecord, NetworkDevice, NetworkLink
from apps.twin.topology_import import without_position
from digital_twin.network_model import NetworkModel
from digital_twin.runtime.persistence import bump_topology_generation, links_in_service, read_status

RETIRED = ElementStatus.DECOMMISSIONED


class LocalCache:
    """A tiny thread-safe in-process cache with expiry (one per API process)."""

    def __init__(self):
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key, ttl: float):
        with self._lock:
            item = self._data.get(key)
            if item and time.monotonic() - item[0] < ttl:
                return item[1]
        return None

    def set(self, key, value) -> None:
        with self._lock:
            if len(self._data) > 500:
                self._data.clear()
            self._data[key] = (time.monotonic(), value)


cache = LocalCache()

# Changes to devices and links made through this process (Waitress runs one). The count is
# part of every cached topology key, so the first request after an edit is built afresh.
_topology_edits = 0
_edits_lock = threading.Lock()


def topology_edits() -> int:
    return _topology_edits


def thresholds() -> dict:
    twin = settings.TWIN
    return {"warning_pct": twin["WARNING_THRESHOLD_PCT"], "critical_pct": twin["CRITICAL_THRESHOLD_PCT"]}


def health(value: float | None, status: str = "up") -> str:
    """Green / yellow / red colour coding of section 3.7 (D1 thresholds)."""
    if status == "down":
        return "down"
    if value is None:
        return "unknown"
    t = thresholds()
    if value >= t["critical_pct"]:
        return "red"
    if value >= t["warning_pct"]:
        return "yellow"
    return "green"


def engine_status() -> dict:
    cached = cache.get("engine_status", 0.5)
    if cached is None:
        cached = read_status() or {}
        cache.set("engine_status", cached)
    return cached


def state_version() -> int:
    return int(engine_status().get("state_version") or 0)


def latest_cycle() -> datetime | None:
    """The newest stored cycle: from the engine's status, or from one indexed lookup."""
    status = engine_status()
    if status.get("last_cycle"):
        return datetime.fromisoformat(status["last_cycle"])
    any_link = NetworkLink.objects.exclude(status=RETIRED).values_list("link_id", flat=True).first()
    if any_link is None:
        return None
    row = (MonitoringRecord.objects.filter(link_id=any_link).order_by("-timestamp")
           .values_list("timestamp", flat=True).first())
    return row


def is_stale(status: dict) -> bool:
    """No stored cycle for three expected cycle periods (wall clock): the data may be out of date."""
    received = status.get("last_received_at")
    if not received:
        return True
    source = status.get("source") or {}
    speed = float(source.get("speed") or 1.0) if source.get("mode") == "live" else 1.0
    period = float(source.get("cycle_seconds") or settings.TWIN["CYCLE_SECONDS"]) / max(speed, 0.001)
    age = (datetime.now(datetime.fromisoformat(received).tzinfo) - datetime.fromisoformat(received)).total_seconds()
    return age > 3 * period + 5


def topology_model() -> NetworkModel:
    """The network model built from the Topology Store (no live state), cached briefly."""
    key = ("topology_model", topology_edits())
    cached = cache.get(key, 30.0)
    if cached is not None:
        return cached
    devices = list(NetworkDevice.objects.exclude(status=RETIRED).values(
        "device_id", "name", "device_type", "location", "status", "configuration"))
    links = list(links_in_service().values(
        "link_id", "source_device_id", "dest_device_id", "capacity_mbps", "status", "routing_cost"))
    twin = settings.TWIN
    model = NetworkModel(devices, links, warning_pct=twin["WARNING_THRESHOLD_PCT"],
                         critical_pct=twin["CRITICAL_THRESHOLD_PCT"],
                         reference_bandwidth_mbps=twin["REFERENCE_BANDWIDTH_MBPS"])
    cache.set(key, model)
    return model


def validation_model() -> NetworkModel:
    """A copy of the topology model that knows the traffic classes currently seen by the engine."""
    model = topology_model().copy()
    model.known_classes = set(engine_status().get("traffic_classes") or [])
    return model


def invalidate_topology(restart_needed: bool = True) -> None:
    """Devices or links were created, edited or imported.

    Cached topology here is rebuilt on the next request. When `restart_needed` (anything but
    map positions changed), the shared counter also tells a running engine (a separate
    process) that it must be restarted to use the change. Positions only feed the map, which
    reads them from the store, so moving a device asks for no restart."""
    global _topology_edits
    with _edits_lock:
        _topology_edits += 1
    if restart_needed:
        bump_topology_generation()


def engine_fields(element) -> dict:
    """The stored fields of a device or link that the engine loads when it starts: all but the map position."""
    values = model_to_dict(element)
    if "configuration" in values:
        values["configuration"] = without_position(values["configuration"])
    return values


def hours_param(request, default: float, maximum: float) -> float:
    try:
        value = float(request.query_params.get("hours", default))
    except (TypeError, ValueError):
        value = default
    return max(0.1, min(value, maximum))


def window(hours: float) -> tuple[datetime | None, datetime | None]:
    end = latest_cycle()
    return (end - timedelta(hours=hours), end) if end else (None, None)
