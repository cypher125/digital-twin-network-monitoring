"""Database access for the engine: the bridge between the twin and the six Chapter 3 tables."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Max, Min

from apps.twin.models import ElementStatus, MonitoringRecord, NetworkDevice, NetworkLink, Prediction
from data_collection.preprocessing import CleanBatch, DeviceRef, LinkRef, TopologyIndex
from digital_twin.network_model import NetworkModel, StatusChange

STATUS_KEY = "engine_status"
GENERATION_KEY = "topology_generation"
RETIRED = ElementStatus.DECOMMISSIONED


def links_in_service():
    """Links that are part of the network: not retired, and neither end device retired.

    A link to a retired device would bring that device back into the network model as a
    bare node, which breaks every analysis of the graph, so it is left out everywhere."""
    return (NetworkLink.objects.exclude(status=RETIRED)
            .exclude(source_device__status=RETIRED).exclude(dest_device__status=RETIRED))


def load_topology() -> tuple[TopologyIndex, list[dict], list[dict]]:
    devices = list(NetworkDevice.objects.exclude(status=RETIRED).values(
        "device_id", "name", "device_type", "location", "status", "configuration"))
    links = list(links_in_service().values(
        "link_id", "source_device_id", "dest_device_id", "capacity_mbps", "status", "routing_cost",
        "source_device__name", "dest_device__name"))
    index = TopologyIndex(
        devices={d["name"]: DeviceRef(d["device_id"], d["name"], d["device_type"],
                                      bool((d["configuration"] or {}).get("internet_egress")))
                 for d in devices},
        links={lk["link_id"]: LinkRef(lk["link_id"], lk["source_device__name"], lk["dest_device__name"],
                                      lk["capacity_mbps"], lk["routing_cost"])
               for lk in links},
    )
    return index, devices, links


def build_model(warning_pct: float, critical_pct: float, reference_bandwidth_mbps: float):
    index, devices, links = load_topology()
    model = NetworkModel(devices, links, warning_pct=warning_pct, critical_pct=critical_pct,
                         reference_bandwidth_mbps=reference_bandwidth_mbps)
    seed_model(model)
    return index, model


def seed_model(model: NetworkModel) -> None:
    """Load the latest stored reading of every link and device, so the replica starts warm."""
    latest_links = (MonitoringRecord.objects.filter(link__isnull=False)
                    .order_by("link_id", "-timestamp").distinct("link_id")
                    .values("link_id", "timestamp", "traffic_in", "traffic_out", "utilisation_pct", "error_count"))
    for row in latest_links:
        if row["link_id"] in model.link_ends:
            edge = model.link(row["link_id"])
            edge.update(traffic_in=row["traffic_in"], traffic_out=row["traffic_out"],
                        utilisation_pct=row["utilisation_pct"], error_count=row["error_count"])
            model.timestamp = max(filter(None, [model.timestamp, row["timestamp"]]))
    latest_devices = (MonitoringRecord.objects.filter(device__isnull=False)
                      .order_by("device_id", "-timestamp").distinct("device_id")
                      .values("device_id", "cpu_util", "traffic_in", "traffic_out", "error_count"))
    for row in latest_devices:
        if row["device_id"] in model.graph:
            model.device(row["device_id"]).update(
                cpu_util=row["cpu_util"], traffic_in=row["traffic_in"],
                traffic_out=row["traffic_out"], error_count=row["error_count"])


def latest_timestamp() -> datetime | None:
    return MonitoringRecord.objects.aggregate(latest=Max("timestamp"))["latest"]


def records_for(batch: CleanBatch) -> list[MonitoringRecord]:
    rows: list[MonitoringRecord] = []
    for reading in batch.links.values():
        if reading.utilisation_pct is None and reading.status != "down":
            continue  # no measurement this cycle (a gap)
        rows.append(MonitoringRecord(
            link_id=reading.link_id, timestamp=batch.timestamp, received_at=batch.received_at,
            traffic_in=reading.traffic_in, traffic_out=reading.traffic_out,
            utilisation_pct=reading.utilisation_pct, error_count=reading.error_count,
            status=reading.status if reading.status != "unknown" else ""))
    for reading in batch.devices.values():
        if reading.status == "unknown":
            continue
        rows.append(MonitoringRecord(
            device_id=reading.device_id, timestamp=batch.timestamp, received_at=batch.received_at,
            traffic_in=reading.traffic_in, traffic_out=reading.traffic_out,
            error_count=reading.error_count, cpu_util=reading.cpu_util, status=reading.status))
    return rows


def write_records(rows: list[MonitoringRecord]) -> None:
    # ignore_conflicts: re-ingesting a cycle never creates duplicates (unique constraints).
    MonitoringRecord.objects.bulk_create(rows, batch_size=2000, ignore_conflicts=True)


def write_status_changes(changes: list[StatusChange]) -> None:
    """Up/down changes seen by the twin. A retired element keeps its status: it has left the network."""
    for change in changes:
        model = NetworkDevice if change.kind == "device" else NetworkLink
        model.objects.filter(pk=change.element_id).exclude(status=RETIRED).update(status=change.new)


def write_capacity_changes(changes: dict[int, float]) -> None:
    """Keep the Topology Store in step when the devices report a new link speed."""
    for link_id, capacity in changes.items():
        NetworkLink.objects.filter(pk=link_id).update(capacity_mbps=capacity)


def write_cycle(batch: CleanBatch, changes: list[StatusChange]) -> int:
    rows = records_for(batch)
    with transaction.atomic():
        write_records(rows)
        write_status_changes(changes)
        write_capacity_changes(batch.capacity_changes)
    return len(rows)


def prune(network_now: datetime, monitoring_days: int, prediction_days: int, batch_size: int = 20000) -> int:
    """Retention (D19), measured in network time (D26). Deletes in small batches."""
    removed = 0
    for model, field_name, days in ((MonitoringRecord, "timestamp", monitoring_days),
                                    (Prediction, "generated_at", prediction_days)):
        cutoff = network_now - timedelta(days=days)
        while True:
            ids = list(model.objects.filter(**{f"{field_name}__lt": cutoff})
                       .values_list("pk", flat=True)[:batch_size])
            if not ids:
                break
            model.objects.filter(pk__in=ids).delete()
            removed += len(ids)
    return removed


def load_history(link_ids: list[int], cycle_seconds: int, since: datetime | None = None,
                 chunk: timedelta = timedelta(days=1)):
    """Link history as time-aligned float32 arrays (times, util, errors), oldest first.

    Read one day at a time with values_list straight into NumPy (never as ORM objects, and
    never every row at once): 14 days of 43 links is about 870,000 rows, too many to hold
    as Python objects on a 4 GB laptop."""
    import numpy as np

    query = MonitoringRecord.objects.filter(link_id__in=link_ids)
    if since is not None:
        query = query.filter(timestamp__gte=since)
    bounds = query.aggregate(first=Min("timestamp"), last=Max("timestamp"))
    if bounds["first"] is None:
        return np.zeros(0), np.zeros((0, len(link_ids)), np.float32), np.zeros((0, len(link_ids)), np.float32)
    first, last = bounds["first"].timestamp(), bounds["last"].timestamp()
    count = int(round((last - first) / cycle_seconds)) + 1
    times = first + np.arange(count) * cycle_seconds
    util = np.full((count, len(link_ids)), np.nan, dtype=np.float32)
    errors = np.full((count, len(link_ids)), np.nan, dtype=np.float32)
    column = {link_id: i for i, link_id in enumerate(link_ids)}
    start = bounds["first"]
    while start <= bounds["last"]:
        part = query.filter(timestamp__gte=start, timestamp__lt=start + chunk).values_list(
            "timestamp", "link_id", "utilisation_pct", "error_count")
        for moment, link_id, value, error_count in part:
            row = int(round((moment.timestamp() - first) / cycle_seconds))
            if value is not None:
                util[row, column[link_id]] = value
            if error_count is not None:
                errors[row, column[link_id]] = error_count
        start += chunk
    return times, util, errors


def write_predictions(rows) -> int:
    """Store one cycle of forecasts (D3). Re-writing the same cycle adds nothing (unique constraint)."""
    Prediction.objects.bulk_create(
        [Prediction(link_id=r.link_id, generated_at=r.generated_at, horizon_minutes=r.horizon_minutes,
                    predicted_utilisation=r.predicted_utilisation, confidence_score=r.confidence_score,
                    is_warning=r.is_warning, model_version=r.model_version) for r in rows],
        batch_size=1000, ignore_conflicts=True)
    return len(rows)


def write_status(status: dict) -> None:
    cache.set(STATUS_KEY, status, timeout=None)


def read_status() -> dict | None:
    return cache.get(STATUS_KEY)


def topology_generation() -> int:
    """How many times devices or links were changed through the API (0 if never)."""
    return int(cache.get(GENERATION_KEY) or 0)


def bump_topology_generation() -> None:
    """Devices or links were created, edited or imported: a running engine needs a restart to see it."""
    try:
        cache.incr(GENERATION_KEY)
    except ValueError:  # the first change since the runtime cache was created
        cache.set(GENERATION_KEY, 1, timeout=None)
