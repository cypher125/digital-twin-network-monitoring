"""Simulation Engine (Figure 3.2): what-if scenarios on a detached copy of the network model (FR4, G3).

It works only on copies and has no access to the network adapters (import-linter contract).
"""
from .recommendations import Recommendation, recommend
from .runner import LinkOutcome, SimulationOutcome, forecast_demands, run_scenario, summarise
from .scenarios import REGISTRY, ScenarioError, ScenarioType, get

__all__ = ["REGISTRY", "LinkOutcome", "Recommendation", "ScenarioError", "ScenarioType", "SimulationOutcome",
           "forecast_demands", "get", "recommend", "run_scenario", "summarise"]
