"""The monitoring cycle (plan section 4.3, Figure 3.4 processes 1.0-5.0).

Each cycle: collect (adapter) -> validate and transform (preprocessing) ->
update the digital twin (network model) -> store (PostgreSQL) -> forecast every
link and update alerts (prediction engine). The dashboard sees the cycle as soon as
it is stored (D28). Fixes for new alerts are worked out on a worker thread, so a new
alert never delays the next poll. Between cycles, queued what-if simulations run on
detached copies of the model.

A poll that comes too late finds that the network has already moved past one or
more cycle boundaries; like a real SNMP poller, the twin cannot read those
boundaries afterwards. Each missed cycle is counted, logged and reported.

The engine runs without manual intervention (NFR2): if the data source or the
database is unreachable it reports the problem and retries with back-off. If the
data source's clock goes backwards it stops ingesting and says so (D26).
"""
from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from django.conf import settings
from django.db import DatabaseError, close_old_connections, connection

from data_collection.network_adapter import NetworkAdapter, RawEvent
from data_collection.preprocessing import (
    CleanBatch,
    ClockWentBackwards,
    Preprocessor,
    TopologyIndex,
)
from digital_twin.network_model import NetworkModel

from . import persistence, simulation_jobs
from .forecasting import ForecastService
from .recommendations import store_for_episode

log = logging.getLogger("digital_twin.engine")


@dataclass
class EngineSettings:
    cycle_seconds: int
    warning_pct: float
    critical_pct: float
    reference_bandwidth_mbps: float
    monitoring_retention_days: int
    prediction_retention_days: int
    poll_offset_seconds: float = 10.0   # network seconds after a cycle boundary before polling
    prune_every_cycles: int = 60
    model_dir: str = ""
    warning_probability: float = 0.5
    reload_models_every_cycles: int = 30

    @classmethod
    def from_django(cls) -> EngineSettings:
        twin = settings.TWIN
        return cls(
            cycle_seconds=twin["CYCLE_SECONDS"],
            warning_pct=twin["WARNING_THRESHOLD_PCT"],
            critical_pct=twin["CRITICAL_THRESHOLD_PCT"],
            reference_bandwidth_mbps=twin["REFERENCE_BANDWIDTH_MBPS"],
            monitoring_retention_days=twin["MONITORING_RETENTION_DAYS"],
            prediction_retention_days=twin["PREDICTION_RETENTION_DAYS"],
            model_dir=twin["MODEL_DIR"],
            warning_probability=twin["WARNING_PROBABILITY"],
        )


class TwinEngine:
    def __init__(self, adapter: NetworkAdapter, config: EngineSettings):
        self.adapter = adapter
        self.config = config
        self.lock = threading.RLock()          # guards the model (main loop + event thread)
        self.stop = threading.Event()
        self.index: TopologyIndex | None = None
        self.model: NetworkModel | None = None
        self.preprocessor: Preprocessor | None = None
        self.state = "starting"
        self.last_error = ""
        self.cycles = 0
        self.last_cycle: CleanBatch | None = None
        self.timings: dict = {}
        self.source: dict = {}
        self.recent_events: deque = deque(maxlen=20)
        self.simulations_run = 0
        self.recommendations_made = 0
        self.forecasting: ForecastService | None = None
        self.state_version = 0   # bumped after every stored cycle and every applied event (D28)
        self.started_at = datetime.now(UTC)
        self.cycles_missed = 0   # cycle boundaries that passed before the engine could poll them
        self.recommendation_queue: queue.Queue = queue.Queue(maxsize=20)
        self.last_recommend_ms: float | None = None
        self._version_lock = threading.Lock()
        # set while the main loop waits for the next cycle boundary: the recommendation worker uses
        # that slack, because a CPU-heavy thread slows the cycle (Python runs one thread at a time)
        self.between_cycles = threading.Event()
        self.between_cycles.set()
        self.topology_generation = 0   # the API's count of topology changes when the topology was loaded

    def _bump_version(self) -> None:
        with self._version_lock:
            self.state_version += 1

    # ------------------------------------------------------------- setup
    def load(self) -> None:
        generation = persistence.topology_generation()   # read first: a change made while loading still counts
        index, model = persistence.build_model(self.config.warning_pct, self.config.critical_pct,
                                               self.config.reference_bandwidth_mbps)
        if not index.devices:
            raise RuntimeError("the Topology Store is empty: run `manage.py import_topology` first")
        self.index, self.model = index, model
        self.topology_generation = generation
        latest = persistence.latest_timestamp()
        self.preprocessor = Preprocessor(index, self.config.cycle_seconds, last_timestamp=latest)
        self.forecasting = ForecastService(
            model, cycle_seconds=self.config.cycle_seconds, critical_pct=self.config.critical_pct,
            warning_probability=self.config.warning_probability, model_dir=self.config.model_dir)
        seeded = self.forecasting.seed_from_database(latest)
        log.info("loaded %d devices and %d links; last stored cycle %s; %d cycles of history in memory",
                 len(index.devices), len(index.links), latest, seeded)

    # ------------------------------------------------------------- cycle
    def run_cycle(self) -> bool:
        """Processes 1.0-3.0 once. Returns True if a new cycle was stored."""
        assert self.preprocessor is not None and self.model is not None
        t0 = time.perf_counter()
        raw = self.adapter.poll()                                  # 1.0 collect
        t1 = time.perf_counter()
        clean = self.preprocessor.process(raw)                    # 2.0 validate and transform
        if clean is None:
            return False
        self._count_missed(clean)
        t2 = time.perf_counter()
        with self.lock:
            changes = self.model.apply(clean)                     # 3.0 update the twin
        t3 = time.perf_counter()
        rows = persistence.write_cycle(clean, changes)            # D2 Monitoring Records
        t4 = time.perf_counter()
        forecasts, started = [], []
        if self.forecasting is not None:
            if clean.capacity_changes:
                self.forecasting.refresh_static(self.model)
            forecasts, started, _ended = self.forecasting.on_cycle(clean)   # 4.0 predictions (D3), alerts
        t5 = time.perf_counter()
        for episode in started:                                   # 5.0 recommendations, on the worker thread
            with self.lock:
                snapshot = self.model.copy()                      # the network as it was when the alert started
            try:
                self.recommendation_queue.put_nowait((snapshot, episode, self.latest_forecast(episode.horizon_minutes)))
            except queue.Full:
                log.warning("recommendation queue full: no fixes worked out for link %s", episode.link_id)
        self.cycles += 1
        self.last_cycle = clean
        self._catch_up_source_time(clean.timestamp)
        self._bump_version()                                      # after the cycle's final commit (D28)
        self.timings = {
            "collect_ms": round((t1 - t0) * 1000, 1),
            "validate_ms": round((t2 - t1) * 1000, 1),
            "update_ms": round((t3 - t2) * 1000, 1),
            "store_ms": round((t4 - t3) * 1000, 1),
            "predict_ms": round((t5 - t4) * 1000, 1),
            "total_ms": round((t5 - t0) * 1000, 1),
            "recommend_ms": self.last_recommend_ms,               # the latest alert's fixes (worker thread)
            "rows": rows,
            "forecasts": len(forecasts),
            "status_changes": len(changes),
        }
        if self.cycles % self.config.prune_every_cycles == 0:
            persistence.prune(clean.timestamp, self.config.monitoring_retention_days,
                              self.config.prediction_retention_days)
        if self.forecasting is not None and self.cycles % self.config.reload_models_every_cycles == 0:
            self.forecasting.reload_if_changed()
        return True

    def seconds_until_next_poll(self) -> float:
        """Wall-clock wait until just after the source's next cycle boundary (network time, D26)."""
        info = self.adapter.describe()
        self.source = {k: info.get(k) for k in ("name", "mode", "speed", "time", "cycle_seconds")}
        if info.get("mode") == "stepped":
            return 2.0  # the clock only moves when the test harness steps it; check again shortly
        speed = float(info.get("speed") or 1.0)
        cycle = float(info.get("cycle_seconds") or self.config.cycle_seconds)
        now = datetime.fromisoformat(info["time"]).timestamp()
        target = math.floor(now / cycle) * cycle + cycle + self.config.poll_offset_seconds
        if self.last_cycle is None or self.last_cycle.timestamp.timestamp() < math.floor(now / cycle) * cycle:
            return 0.0  # a boundary has passed that we have not stored yet: poll now
        return max(0.0, (target - now) / speed)

    def _catch_up_source_time(self, stored: datetime) -> None:
        """The source time was read before waiting for this cycle: never publish it earlier than the
        cycle just stored, or the dashboard's network clock runs up to a cycle behind its data."""
        try:
            behind = datetime.fromisoformat(self.source["time"]).timestamp() < stored.timestamp()
        except (KeyError, TypeError, ValueError):   # no source time read yet
            behind = True
        if behind:
            self.source = {**self.source, "time": stored.isoformat()}

    # ------------------------------------------------------------ events
    def apply_event(self, event: RawEvent) -> None:
        """Event-driven update (FR2): an up/down notification changes the twin immediately."""
        assert self.index is not None and self.model is not None
        new_status = "down" if event.type.endswith("_down") else "up"
        if event.type.startswith("link"):
            a, _, b = event.element.partition("|")
            link = self.index.link_between(a, b)
            if link is None:
                return
            kind, element_id = "link", link.link_id
        else:
            device = self.index.devices.get(event.element)
            if device is None:
                return
            kind, element_id = "device", device.device_id
        with self.lock:
            change = self.model.set_status(kind, element_id, new_status)
        if change:
            persistence.write_status_changes([change])
            self._bump_version()
        applied_at = datetime.now(UTC)
        self.recent_events.appendleft({
            "type": event.type, "element": event.element, "network_time": event.time.isoformat(),
            "applied_ms": round((applied_at - event.received_at).total_seconds() * 1000, 1),
        })
        log.info("event %s %s applied", event.type, event.element)
        if change:
            self.publish_status()  # the dashboard sees the new state version within a poll (D28)

    def _event_loop(self) -> None:
        backoff = 1.0
        try:
            while not self.stop.is_set():
                try:
                    for event in self.adapter.events(wait_seconds=20):
                        self.apply_event(event)
                    backoff = 1.0
                except (httpx.HTTPError, DatabaseError) as exc:
                    log.warning("event listener: %s", exc)
                    close_old_connections()
                    self.stop.wait(backoff)
                    backoff = min(backoff * 2, 30.0)
        finally:
            connection.close()  # this thread's own database connection

    # ------------------------------------------------------------ status
    def topology_changed(self) -> bool:
        """Devices or links were changed through the API since load(): a restart is needed to use them."""
        return self.index is not None and persistence.topology_generation() != self.topology_generation

    def status(self) -> dict:
        last = self.last_cycle
        return {
            "state": self.state,
            "last_error": self.last_error,
            "heartbeat": datetime.now(UTC).isoformat(),
            "started_at": self.started_at.isoformat(),
            "cycles_stored": self.cycles,
            "last_cycle": last.timestamp.isoformat() if last else None,
            "last_received_at": last.received_at.isoformat() if last else None,
            "timings": self.timings,
            "data_quality": last.quality.as_dict() if last else {},
            "source": self.source,
            "recent_events": list(self.recent_events),
            "simulations_run": self.simulations_run,
            "recommendations_made": self.recommendations_made,
            "forecasting": self.forecasting.status() if self.forecasting else None,
            "traffic_classes": sorted(self.model.traffic_classes()) if self.model else [],
            "state_version": self.state_version,
            "cycles_missed": self.cycles_missed,
            "recommendations_pending": self.recommendation_queue.qsize(),
            "topology_changed": self.topology_changed(),
        }

    def publish_status(self) -> None:
        try:
            persistence.write_status(self.status())
        except DatabaseError as exc:  # the database being down must not stop the engine
            log.warning("could not publish status: %s", exc)

    # ------------------------------------------------------ late polls
    def _count_missed(self, clean: CleanBatch) -> int:
        """Cycle boundaries between the last stored cycle and this one that were never polled."""
        if self.last_cycle is None:
            return 0           # the first cycle after a start: the engine was off, not late
        step = (clean.timestamp - self.last_cycle.timestamp).total_seconds() / self.config.cycle_seconds
        missed = max(0, round(step) - 1)
        if missed:
            self.cycles_missed += missed
            live = self.source.get("mode") == "live"
            speed = float(self.source.get("speed") or 1.0) if live else 1.0
            log.warning("missed %d cycle(s) before %s: the previous cycle took %s ms, and at %g x speed "
                        "a cycle lasts %.1f s", missed, clean.timestamp.isoformat(), self.timings.get("total_ms"),
                        speed, self.config.cycle_seconds / speed)
        return missed

    # --------------------------------------------------- recommendations
    def recommend_next(self, timeout: float = 1.0) -> bool:
        """Work out and store the fixes for one new alert, if one is waiting. True if one was done."""
        try:
            snapshot, episode, predicted = self.recommendation_queue.get(timeout=timeout)
        except queue.Empty:
            return False
        began = time.perf_counter()
        try:
            self.recommendations_made += store_for_episode(snapshot, episode, predicted)
        except DatabaseError as exc:
            log.warning("recommendations for link %s: %s", episode.link_id, exc)
            close_old_connections()
            return False
        self.last_recommend_ms = round((time.perf_counter() - began) * 1000, 1)
        self._bump_version()       # the alert now carries its recommendations
        self.publish_status()
        return True

    def _recommendation_loop(self) -> None:
        try:
            while not self.stop.is_set():
                if not self.between_cycles.wait(timeout=1.0):
                    continue                              # a cycle is running: start nothing new now
                try:
                    self.recommend_next(timeout=1.0)
                except Exception:  # keep the worker alive; report it (NFR2)
                    log.exception("recommendations failed")
                    close_old_connections()
        finally:
            connection.close()  # this thread's own database connection

    # -------------------------------------------------------------- main
    def latest_forecast(self, horizon_minutes: int) -> dict[int, float] | None:
        """{link_id: predicted %} at a horizon, for forecast-based simulations and recommendations."""
        return self.forecasting.latest_forecast(horizon_minutes) if self.forecasting else None

    def _serve_simulations(self) -> None:
        if self.model is None:
            return
        try:
            done = simulation_jobs.run_pending(self.model, self.lock, forecast=self.latest_forecast)
            self.simulations_run += done
        except DatabaseError as exc:
            log.warning("simulation queue: %s", exc)
            close_old_connections()

    def _wait_serving_jobs(self, seconds: float) -> bool:
        """Wait until the next poll, running queued simulations meanwhile (checked every second).

        Returns True if the engine was asked to stop."""
        deadline = time.monotonic() + seconds
        while True:
            self._serve_simulations()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self.stop.is_set()
            if self.stop.wait(min(1.0, remaining)):
                return True

    def run_forever(self) -> None:
        self.load()
        listener = threading.Thread(target=self._event_loop, name="twin-events", daemon=True)
        listener.start()
        worker = threading.Thread(target=self._recommendation_loop, name="twin-recommendations", daemon=True)
        worker.start()
        backoff = 1.0
        while not self.stop.is_set():
            try:
                close_old_connections()
                wait = self.seconds_until_next_poll()
                if wait > 0 and self._wait_serving_jobs(min(wait, 60.0)):
                    break
                self.between_cycles.clear()
                try:
                    stored = self.run_cycle()
                finally:
                    self.between_cycles.set()
                if stored:
                    self.state, self.last_error = "running", ""
                elif self.source.get("mode") == "stepped":
                    self.state = "paused: the data source clock is stepped by the test harness"
                backoff = 1.0
            except ClockWentBackwards as exc:
                self.state, self.last_error = "paused: the data source clock went backwards", str(exc)
                log.error("%s", exc)
                self.stop.wait(10)
            except httpx.HTTPError as exc:
                self.state, self.last_error = "waiting for the data source", f"{type(exc).__name__}: {exc}"
                log.warning("data source: %s", exc)
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)
            except DatabaseError as exc:
                self.state, self.last_error = "waiting for the database", f"{type(exc).__name__}: {exc}"
                log.warning("database: %s", exc)
                close_old_connections()
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 30.0)
            except Exception as exc:  # keep running; report it (NFR2)
                self.state, self.last_error = "error", f"{type(exc).__name__}: {exc}"
                log.exception("cycle failed")
                self.stop.wait(5)
            finally:
                self.publish_status()
        self.state = "stopped"
        self.publish_status()
