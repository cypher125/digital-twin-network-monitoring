"""Devices and links (D1) with their recent history (D2) and forecasts (D3): UC1 detail and UC2 chart."""
from datetime import timedelta

from django.db import connection
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.twin.models import NetworkDevice, NetworkLink, Prediction

from ..permissions import IsSeniorOrReadOnly
from ..serializers import DeviceSerializer, LinkSerializer
from ..services import engine_fields, hours_param, invalidate_topology, latest_cycle, thresholds


def series(column: str, element_id: int, hours: float) -> list[dict]:
    """Recent history of one device or link. Raw cycles up to 6 h; 5-minute buckets up to 48 h; hourly beyond."""
    end = latest_cycle()
    if end is None:
        return []
    start = end - timedelta(hours=hours)
    bucket = None if hours <= 6 else ("5 minutes" if hours <= 48 else "1 hour")
    if bucket is None:
        sql = (f"SELECT timestamp, utilisation_pct, utilisation_pct, traffic_in, traffic_out, error_count, cpu_util, "
               f"status FROM monitoring_record WHERE {column} = %s AND timestamp > %s AND timestamp <= %s "
               f"ORDER BY timestamp")
        params = [element_id, start, end]
    else:
        sql = (f"SELECT date_bin(%s::interval, timestamp, TIMESTAMPTZ '2000-01-01') AS t, avg(utilisation_pct), "
               f"max(utilisation_pct), avg(traffic_in), avg(traffic_out), sum(error_count), avg(cpu_util), "
               f"min(status) FROM monitoring_record WHERE {column} = %s AND timestamp > %s AND timestamp <= %s "
               f"GROUP BY t ORDER BY t")
        params = [bucket, element_id, start, end]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return [{"t": r[0].isoformat(), "utilisation_pct": _round(r[1]), "max_utilisation_pct": _round(r[2]),
             "traffic_in": _round(r[3]), "traffic_out": _round(r[4]), "error_count": r[5], "cpu_util": _round(r[6]),
             "status": r[7]} for r in rows]


def _round(value, digits: int = 2):
    return None if value is None else round(float(value), digits)


class DeviceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Devices of the Topology Store. Retire a device by setting status to 'decommissioned'
    (there is no delete: its history must be kept)."""

    queryset = NetworkDevice.objects.all().order_by("device_id")
    serializer_class = DeviceSerializer
    permission_classes = [IsSeniorOrReadOnly]
    filterset_fields = ["device_type", "status", "location"]
    pagination_class = None

    def perform_create(self, serializer):
        element = serializer.save()
        invalidate_topology()
        audit(self.request, f"{self.basename}_created", id=element.pk)

    def perform_update(self, serializer):
        before = engine_fields(serializer.instance)   # save() changes this same object
        element = serializer.save()
        # a save that changes nothing, or only a map position, needs no engine restart
        invalidate_topology(restart_needed=engine_fields(element) != before)
        audit(self.request, f"{self.basename}_updated", id=element.pk, fields=",".join(sorted(serializer.validated_data)))

    @action(detail=True, methods=["get"])
    def metrics(self, request, pk=None):
        device = self.get_object()
        hours = hours_param(request, 1, 14 * 24)
        return Response({"device_id": device.device_id, "name": device.name, "hours": hours,
                         "thresholds": thresholds(), "points": series("device_id", device.device_id, hours)})


class LinkViewSet(DeviceViewSet):
    """Links of the Topology Store. Retire a link by setting status to 'decommissioned'."""

    queryset = NetworkLink.objects.select_related("source_device", "dest_device").order_by("link_id")
    serializer_class = LinkSerializer
    filterset_fields = ["status"]

    @action(detail=True, methods=["get"])
    def metrics(self, request, pk=None):
        link = self.get_object()
        hours = hours_param(request, 1, 14 * 24)
        return Response({"link_id": link.link_id, "label": str(link), "capacity_mbps": link.capacity_mbps,
                         "hours": hours, "thresholds": thresholds(), "points": series("link_id", link.link_id, hours)})

    @action(detail=True, methods=["get"])
    def forecast(self, request, pk=None):
        """History plus the latest predicted trajectory, for the trend and forecast chart (UC2)."""
        link = self.get_object()
        hours = hours_param(request, 6, 14 * 24)
        latest = latest_cycle()
        predictions = []
        if latest is not None:
            predictions = list(Prediction.objects.filter(link=link, generated_at=latest).order_by("horizon_minutes")
                               .values("horizon_minutes", "predicted_utilisation", "confidence_score", "is_warning",
                                       "model_version"))
        trajectory = [{"t": (latest + timedelta(minutes=p["horizon_minutes"])).isoformat(),
                       "horizon_minutes": p["horizon_minutes"], "predicted_pct": round(p["predicted_utilisation"], 2),
                       "confidence": round(p["confidence_score"], 3), "warning": p["is_warning"]}
                      for p in predictions]
        return Response({"link_id": link.link_id, "label": str(link), "capacity_mbps": link.capacity_mbps,
                         "generated_at": latest.isoformat() if latest else None, "thresholds": thresholds(),
                         "model_version": predictions[0]["model_version"] if predictions else None,
                         "history": series("link_id", link.link_id, hours), "forecast": trajectory})
