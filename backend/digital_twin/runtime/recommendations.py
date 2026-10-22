"""Store recommendations for new alert episodes (plan section 7.7), owned by the system account.

They are kept as SimulationScenario + SimulationResult rows, so they stay inside the
six tables and appear in the audit trail like any other simulation.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.accounts.roles import ensure_system_user
from apps.twin.models import RunStatus, SimulationResult, SimulationScenario
from digital_twin.network_model import NetworkModel
from digital_twin.prediction_engine import Episode
from digital_twin.simulation_engine import recommend

log = logging.getLogger("digital_twin.recommendations")


def store_for_episode(model: NetworkModel, episode: Episode, predicted_pct: dict[int, float] | None) -> int:
    recommendations = recommend(model, episode.link_id, predicted_pct,
                                basis=f"forecast +{episode.horizon_minutes} min" if predicted_pct else "current")
    system = ensure_system_user()
    trigger = {"kind": "recommendation", "link_id": episode.link_id,
               "episode_started": episode.started_at.isoformat(), "predicted_time": episode.predicted_time.isoformat()}
    for rank, rec in enumerate(recommendations, start=1):
        scenario = SimulationScenario.objects.create(
            created_by=system,
            scenario_name=f"Recommendation {rank}: {rec.title}"[:120],
            scenario_type=rec.scenario_type,
            parameters={**rec.parameters, "trigger": {**trigger, "rank": rank, "advice": rec.kind}},
        )
        SimulationResult.objects.create(
            scenario=scenario, run_by=system, executed_at=timezone.now(), status=RunStatus.COMPLETED,
            predicted_utilisation=rec.outcome.predicted_utilisation(),
            bottleneck_links=rec.outcome.bottleneck_links(),
            result_summary={**rec.outcome.result_summary(), "request": {"basis": rec.outcome.basis}},
        )
    log.info("%d recommendation(s) for %s", len(recommendations), model.link_label(episode.link_id))
    return len(recommendations)
