"""System status, settings, topology import and user list (Administration page)."""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.audit import audit
from apps.accounts.roles import SYSTEM_USERNAME, role_of
from apps.twin.topology_import import import_topology

from ..permissions import IsSenior
from ..services import engine_status, invalidate_topology, is_stale, thresholds

MAX_IMPORT_BYTES = 2 * 1024 * 1024
# The six tables in Table 3.2 order. The small ones are counted exactly. The two large ones use
# PostgreSQL's estimate, or are counted while it has none (-1 or 0 until the table is first analysed).
TABLES = ("network_device", "network_link", "monitoring_record", "prediction", "simulation_scenario",
          "simulation_result")
ESTIMATED = ("monitoring_record", "prediction")


def active_models() -> list[dict]:
    model_dir = Path(settings.TWIN["MODEL_DIR"])
    active_file = model_dir / "active.json"
    if not active_file.exists():
        return []
    out = []
    for kind, version in json.loads(active_file.read_text(encoding="utf-8")).items():
        meta_file = model_dir / version / "meta.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        forest = meta.get("metrics", {}).get("random_forest", {})
        persistence = meta.get("metrics", {}).get("persistence", {})
        warnings = meta.get("classification", {}).get("random_forest_classifier", {})
        out.append({
            "kind": kind, "version": version, "created_at": meta.get("created_at"),
            "window": meta.get("window"), "rows": meta.get("rows"),
            "mae_by_horizon": {h: round(v["mae"], 3) for h, v in forest.items()},
            "persistence_mae_by_horizon": {h: round(v["mae"], 3) for h, v in persistence.items()},
            "warning_quality": {h: {"precision": round(v["precision"], 3), "recall": round(v["recall"], 3)}
                                for h, v in warnings.items()},
            "warning_threshold": (meta.get("rows") or {}).get("warning_threshold"),
            "size_bytes": meta.get("sizes", {}).get("file_bytes"),
        })
    return out


def database_figures() -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        size = cursor.fetchone()[0]
        # table names are the constants above, never user input
        cursor.execute("SELECT relname, reltuples::bigint FROM pg_class WHERE oid IN ("
                       + ", ".join(f"'{t}'::regclass" for t in ESTIMATED) + ")")
        estimates = {table: rows for table, rows in cursor.fetchall() if rows > 0}
        exact = [t for t in TABLES if t not in estimates]
        cursor.execute(" UNION ALL ".join(f"SELECT '{t}', count(*) FROM {t}" for t in exact))
        counts = {**estimates, **dict(cursor.fetchall())}
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0].split(" on ")[0]
    return {"size_bytes": size, "approximate_rows": {t: counts[t] for t in TABLES}, "exact_tables": exact,
            "server": version}


class StatusView(APIView):
    def get(self, request):
        engine = engine_status()
        return Response({
            "engine": {**engine, "stale": is_stale(engine)},
            "models": active_models(),
            "database": database_figures(),
            "thresholds": thresholds(),
        })


class SettingsView(APIView):
    def get(self, request):
        twin = settings.TWIN
        return Response({
            **thresholds(),
            "cycle_seconds": twin["CYCLE_SECONDS"],
            "horizons_minutes": twin["HORIZONS_MINUTES"],
            "warning_probability": twin["WARNING_PROBABILITY"],
            "monitoring_retention_days": twin["MONITORING_RETENTION_DAYS"],
            "prediction_retention_days": twin["PREDICTION_RETENTION_DAYS"],
            "poll_seconds": twin["DASHBOARD_POLL_SECONDS"],
            "time_zone": settings.TIME_ZONE,
        })


class TopologyImportView(APIView):
    """Import devices and links (section 1.4). Validates everything first; `dry_run` reports without saving."""

    permission_classes = [IsSenior]

    def post(self, request):
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_IMPORT_BYTES:
            return Response({"detail": "The file is too large (2 MB at most)."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        raw = request.data.get("topology") if isinstance(request.data, dict) else None
        upload = request.FILES.get("file")
        if upload is not None:
            import yaml
            try:
                raw = yaml.safe_load(upload.read().decode("utf-8"))
            except (UnicodeDecodeError, yaml.YAMLError):
                return Response({"detail": "The file is not valid YAML or JSON."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(raw, dict):
            return Response({"detail": "Send a topology object or a YAML/JSON file."},
                            status=status.HTTP_400_BAD_REQUEST)
        dry_run = str(request.data.get("dry_run", "false")).lower() in {"1", "true", "yes"}
        report = import_topology(raw, dry_run=dry_run)
        audit(request, "topology_import", dry_run=dry_run, ok=report.ok, devices_created=report.devices_created,
              devices_updated=report.devices_updated, links_created=report.links_created,
              links_updated=report.links_updated, links_skipped=len(report.links_skipped), errors=len(report.errors))
        if report.ok and not dry_run:
            invalidate_topology(restart_needed=report.restart_needed)
        # restart_needed: the engine needs a restart to use the import (or would, after a dry run)
        body = {"ok": report.ok, "dry_run": dry_run, "errors": report.errors,
                "devices_created": report.devices_created, "devices_updated": report.devices_updated,
                "links_created": report.links_created, "links_updated": report.links_updated,
                "links_skipped": report.links_skipped, "restart_needed": report.restart_needed}
        return Response(body, status=status.HTTP_200_OK if report.ok else status.HTTP_400_BAD_REQUEST)


class UsersView(APIView):
    """Administrator accounts (managed in the admin site; this list feeds the Administration page)."""

    permission_classes = [IsSenior]

    def get(self, request):
        users = User.objects.exclude(username=SYSTEM_USERNAME).order_by("username")
        return Response([{"username": u.username, "full_name": u.get_full_name(), "role": role_of(u),
                          "is_active": u.is_active, "last_login": u.last_login} for u in users])
