"""Predictive congestion alerts (UC2 "Receive predictive congestion alert", FR3, gap G2)."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import SYSTEM_USERNAME
from apps.twin.models import NetworkLink, Prediction, RunStatus, SimulationResult
from digital_twin.prediction_engine import replay

from ..services import cache, engine_status, hours_param, latest_cycle, thresholds


def link_labels() -> dict[int, str]:
    return {lk["link_id"]: f"{lk['source_device__name']} <-> {lk['dest_device__name']}"
            for lk in NetworkLink.objects.values("link_id", "source_device__name", "dest_device__name")}


def trained_at(version: str | None) -> str | None:
    """When a trained model was made (from its meta.json, in UTC), so the page can show it in WAT.

    A saved model never changes, so the answer is cached; one small file is read per version."""
    if not version or version.startswith(".") or Path(version).name != version:   # a folder name, not a path
        return None
    cached = cache.get(("trained_at", version), 3600.0)
    if cached is None:
        meta_file = Path(settings.TWIN["MODEL_DIR"]) / version / "meta.json"
        try:
            cached = str(json.loads(meta_file.read_text(encoding="utf-8")).get("created_at") or "")
        except (OSError, ValueError):
            cached = ""
        cache.set(("trained_at", version), cached)
    return cached or None


def recommendations_for(link_id: int, episode_started: str) -> list[dict]:
    results = (SimulationResult.objects
               .filter(scenario__created_by__username=SYSTEM_USERNAME, status=RunStatus.COMPLETED,
                       scenario__parameters__trigger__link_id=link_id,
                       scenario__parameters__trigger__episode_started=episode_started)
               .select_related("scenario").order_by("scenario__scenario_id"))
    out = []
    for r in results:
        trigger = r.scenario.parameters.get("trigger", {})
        summary = r.result_summary or {}
        out.append({
            "result_id": r.result_id, "scenario_id": r.scenario_id,
            "title": r.scenario.scenario_name.split(": ", 1)[-1],
            "advice": trigger.get("advice", "immediate"), "rank": trigger.get("rank"),
            "scenario_type": r.scenario.scenario_type,
            "parameters": {k: v for k, v in r.scenario.parameters.items() if k != "trigger"},
            "summary": summary.get("summary", ""),
            "link_after_pct": (r.predicted_utilisation or {}).get(str(link_id)),
            "max_after": summary.get("max_after"),
        })
    return out


class ActiveAlertsView(APIView):
    def get(self, request):
        status = engine_status()
        forecasting = status.get("forecasting") or {}
        episodes = forecasting.get("active_alerts") or []
        latest = latest_cycle()
        labels = link_labels()
        current, trajectories = {}, {}
        if latest is not None and episodes:
            ids = [e["link_id"] for e in episodes]
            from apps.twin.models import MonitoringRecord
            current = dict(MonitoringRecord.objects.filter(timestamp=latest, link_id__in=ids)
                           .values_list("link_id", "utilisation_pct"))
            for p in Prediction.objects.filter(generated_at=latest, link_id__in=ids).order_by("horizon_minutes"):
                trajectories.setdefault(p.link_id, []).append(
                    {"horizon_minutes": p.horizon_minutes, "predicted_pct": round(p.predicted_utilisation, 1),
                     "confidence": round(p.confidence_score, 3), "warning": p.is_warning})
        alerts = []
        for e in sorted(episodes, key=lambda x: x["predicted_time"]):
            minutes_until = None
            if latest is not None:
                minutes_until = round((datetime.fromisoformat(e["predicted_time"]) - latest).total_seconds() / 60)
            alerts.append({
                **e,
                "label": labels.get(e["link_id"], f"link {e['link_id']}"),
                "current_pct": current.get(e["link_id"]),
                "minutes_until": minutes_until,
                "kind": "critical_now" if e.get("critical_now") else "predicted",
                "confidence_band": band(e.get("confidence", 0)),
                "trajectory": trajectories.get(e["link_id"], []),
                "recommendations": recommendations_for(e["link_id"], e["started_at"]),
            })
        return Response({"generated_at": latest.isoformat() if latest else None, "thresholds": thresholds(),
                         "model": forecasting.get("active_model"), "model_kind": forecasting.get("model_kind"),
                         "model_trained_at": trained_at(forecasting.get("active_model")),
                         "history_cycles": forecasting.get("history_cycles"),
                         "short_model_needs": forecasting.get("short_model_needs"), "alerts": alerts})


def band(confidence: float) -> str:
    """D5: High (>= 0.8), Medium (0.6-0.8), Low."""
    return "High" if confidence >= 0.8 else "Medium" if confidence >= 0.6 else "Low"


class AlertHistoryView(APIView):
    """Episodes rebuilt from the stored predictions with the engine's own hysteresis rule."""

    def get(self, request):
        hours = hours_param(request, 24, 48)
        latest = latest_cycle()
        if latest is None:
            return Response({"episodes": []})
        since = latest - timedelta(hours=hours)
        warned = list(Prediction.objects.filter(generated_at__gte=since, is_warning=True)
                      .values_list("link_id", flat=True).distinct())
        rows = Prediction.objects.filter(generated_at__gte=since, link_id__in=warned).values_list(
            "link_id", "generated_at", "horizon_minutes", "predicted_utilisation", "confidence_score", "is_warning")
        ended, active = replay(rows)
        labels = link_labels()
        episodes = [{**e.as_dict(), "label": labels.get(e.link_id, f"link {e.link_id}"),
                     "active": e.ended_at is None} for e in ended + active]
        episodes.sort(key=lambda e: e["started_at"], reverse=True)
        return Response({"hours": hours, "episodes": episodes})
