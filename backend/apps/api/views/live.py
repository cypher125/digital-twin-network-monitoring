"""Live state for the dashboard (UC1, FR5, NFR1; plan decision D28)."""
from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.twin.models import MonitoringRecord, NetworkDevice, Prediction
from digital_twin.runtime.persistence import links_in_service

from ..services import (
    RETIRED,
    cache,
    engine_status,
    health,
    is_stale,
    latest_cycle,
    thresholds,
    topology_edits,
    topology_model,
)


class LiveView(APIView):
    """Polled every second: tells the dashboard whether anything new has been stored."""

    def get(self, request):
        status = engine_status()
        source = status.get("source") or {}
        return Response({
            "state_version": int(status.get("state_version") or 0),
            "last_cycle": status.get("last_cycle"),
            "network_time": source.get("time"),
            "mode": source.get("mode"),
            "speed": source.get("speed"),
            "engine_state": status.get("state", "not running"),
            "last_error": status.get("last_error", ""),
            "stale": is_stale(status),
            "poll_seconds": settings.TWIN["DASHBOARD_POLL_SECONDS"],
        })


def build_topology(state_version: int) -> dict:
    devices = list(NetworkDevice.objects.exclude(status=RETIRED).values(
        "device_id", "name", "device_type", "ip_address", "location", "status", "configuration"))
    links = list(links_in_service().values(
        "link_id", "source_device_id", "dest_device_id", "source_device__name", "dest_device__name",
        "capacity_mbps", "status", "routing_cost"))
    latest = latest_cycle()
    readings = {}
    forecasts: dict[int, list] = {}
    if latest is not None:
        for row in MonitoringRecord.objects.filter(timestamp=latest).values(
                "device_id", "link_id", "utilisation_pct", "traffic_in", "traffic_out", "error_count", "cpu_util"):
            key = ("link", row["link_id"]) if row["link_id"] else ("device", row["device_id"])
            readings[key] = row
        for row in Prediction.objects.filter(generated_at=latest).values(
                "link_id", "horizon_minutes", "predicted_utilisation", "confidence_score", "is_warning"):
            forecasts.setdefault(row["link_id"], []).append(row)
    structure = topology_model().structural_bottlenecks()
    bridges, articulation = set(structure["bridge_links"]), set(structure["articulation_devices"])
    most_used = set(structure["most_used_links"])
    critical = thresholds()["critical_pct"]

    device_out = []
    for d in devices:
        reading = readings.get(("device", d["device_id"]), {})
        config = d["configuration"] or {}
        device_out.append({
            "device_id": d["device_id"], "name": d["name"], "device_type": d["device_type"],
            "ip_address": d["ip_address"], "location": d["location"], "status": d["status"],
            "role": config.get("role", ""), "zone": config.get("zone", ""), "position": config.get("position"),
            "cpu_util": reading.get("cpu_util"), "traffic_in": reading.get("traffic_in"),
            "traffic_out": reading.get("traffic_out"),
            "health": health(reading.get("cpu_util"), d["status"]),
            "single_point_of_failure": d["device_id"] in articulation,
        })
    link_out = []
    for lk in links:
        reading = readings.get(("link", lk["link_id"]), {})
        rows = sorted(forecasts.get(lk["link_id"], []), key=lambda r: r["horizon_minutes"])
        warning = next((r for r in rows if r["is_warning"]), None)
        link_out.append({
            "link_id": lk["link_id"], "source_id": lk["source_device_id"], "dest_id": lk["dest_device_id"],
            "label": f"{lk['source_device__name']} <-> {lk['dest_device__name']}",
            "capacity_mbps": lk["capacity_mbps"], "status": lk["status"],
            "utilisation_pct": reading.get("utilisation_pct"),
            "traffic_out": reading.get("traffic_out"), "traffic_in": reading.get("traffic_in"),
            "error_count": reading.get("error_count"),
            "health": health(reading.get("utilisation_pct"), lk["status"]),
            "single_point_of_failure": lk["link_id"] in bridges,
            "most_used": lk["link_id"] in most_used,
            "forecast": [{"horizon_minutes": r["horizon_minutes"], "predicted_pct": r["predicted_utilisation"],
                          "confidence": r["confidence_score"], "warning": r["is_warning"]} for r in rows],
            "warning": None if warning is None else {
                "horizon_minutes": warning["horizon_minutes"], "confidence": warning["confidence_score"],
                "predicted_pct": warning["predicted_utilisation"]},
        })
    measured = [lk for lk in link_out if lk["utilisation_pct"] is not None and lk["status"] != "down"]
    peak = max(measured, key=lambda lk: lk["utilisation_pct"], default=None)
    by_health: dict[str, int] = {}
    for lk in link_out:
        by_health[lk["health"]] = by_health.get(lk["health"], 0) + 1
    return {
        "state_version": state_version,
        "last_cycle": latest.isoformat() if latest else None,
        "thresholds": thresholds(),
        "devices": device_out,
        "links": link_out,
        "summary": {
            "devices_up": sum(1 for d in devices if d["status"] == "up"),
            "devices_total": len(devices),
            "links_total": len(links),
            "links_by_health": by_health,
            "average_utilisation_pct": round(sum(lk["utilisation_pct"] for lk in measured) / len(measured), 2)
            if measured else None,
            "peak_link": None if peak is None else {"link_id": peak["link_id"], "label": peak["label"],
                                                   "utilisation_pct": peak["utilisation_pct"]},
            "links_warned": sum(1 for lk in link_out if lk["warning"]),
            "links_critical_now": sum(1 for lk in measured if lk["utilisation_pct"] >= critical),
        },
        "horizons_minutes": settings.TWIN["HORIZONS_MINUTES"],
    }


class TopologyView(APIView):
    """Devices and links with their latest state, colours, forecasts and structural bottlenecks (UC1)."""

    def get(self, request):
        version = int(engine_status().get("state_version") or 0)
        key = ("topology", version, topology_edits())   # an edit or import is shown at once, not next cycle
        payload = cache.get(key, 5.0)
        if payload is None:
            payload = build_topology(version)
            cache.set(key, payload)
        return Response(payload)
