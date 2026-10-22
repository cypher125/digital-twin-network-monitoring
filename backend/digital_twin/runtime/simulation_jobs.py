"""Execute queued simulation runs between monitoring cycles (plan decision D10, Figure 3.4 process 5.0).

The API stores a SimulationResult with status "queued" (and the run options in
result_summary["request"]). The engine claims it, runs the scenario on a detached
snapshot of the live model, and stores the outcome in the SimulationResult fields
of Table 3.2.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

from apps.twin.models import RunStatus, SimulationResult
from digital_twin.network_model import NetworkModel
from digital_twin.simulation_engine import ScenarioError, run_scenario

log = logging.getLogger("digital_twin.simulation")

ForecastProvider = Callable[[int], dict[int, float] | None]   # horizon minutes -> {link_id: %}


def claim_next() -> SimulationResult | None:
    """Take the oldest queued run, safely even if several engines were ever running."""
    with transaction.atomic():
        job = (SimulationResult.objects.select_for_update(skip_locked=True)
               .filter(status=RunStatus.QUEUED).order_by("requested_at").select_related("scenario").first())
        if job is not None:
            job.status = RunStatus.RUNNING
            job.save(update_fields=["status"])
        return job


def execute(job: SimulationResult, model: NetworkModel, forecast: ForecastProvider | None = None) -> None:
    scenario = job.scenario
    request = dict((job.result_summary or {}).get("request") or {})
    started = time.perf_counter()
    try:
        predicted, basis = None, "current"
        if request.get("basis") == "forecast":
            horizon = int(request.get("horizon_minutes", 30))
            predicted = forecast(horizon) if forecast else None
            if not predicted:
                raise ScenarioError("No forecasts are available yet, so the scenario cannot use the forecast state.")
            basis = f"forecast +{horizon} min"
        outcome = run_scenario(model, scenario.scenario_type, scenario.parameters, predicted_pct=predicted,
                               basis=basis)
        job.predicted_utilisation = outcome.predicted_utilisation()
        job.bottleneck_links = outcome.bottleneck_links()
        job.result_summary = {**outcome.result_summary(), "request": request,
                              "runtime_ms": round((time.perf_counter() - started) * 1000, 1)}
        job.status = RunStatus.COMPLETED
    except ScenarioError as exc:
        job.result_summary = {"request": request, "error": str(exc)}
        job.status = RunStatus.FAILED
    except Exception as exc:  # recorded so the activity log stays complete (Table 3.2)
        log.exception("simulation %s failed", job.pk)
        job.result_summary = {"request": request, "error": f"Internal error: {type(exc).__name__}"}
        job.status = RunStatus.FAILED
    job.executed_at = timezone.now()
    job.save(update_fields=["predicted_utilisation", "bottleneck_links", "result_summary", "status", "executed_at"])


def run_pending(model: NetworkModel, lock: threading.RLock, *, forecast: ForecastProvider | None = None,
                time_budget_s: float = 2.0) -> int:
    """Run queued simulations for at most `time_budget_s`, so the next cycle always starts on time."""
    began, done = time.perf_counter(), 0
    while time.perf_counter() - began < time_budget_s:
        job = claim_next()
        if job is None:
            break
        with lock:
            snapshot = model.copy()   # consistent view; the event thread cannot change it mid-run
        execute(job, snapshot, forecast)
        done += 1
    return done
