"""The prediction engine (process 4.0): features, training, registry, live forecasting and alerts."""
import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from digital_twin.prediction_engine import (
    AlertTracker,
    FeatureSpec,
    Forecast,
    HistoryBuffer,
    Predictor,
    build_features,
    load_active,
    promote,
    replay,
    save,
    train,
)
from digital_twin.prediction_engine.features import (
    _reference_rows,
    _rolling,
    _slope,
    fill_short_gaps,
)
from tests.conftest import START, emulated_history

HORIZONS = (5, 10, 15, 30)
FULL = FeatureSpec(60, HORIZONS, full=True)
SHORT = FeatureSpec(60, HORIZONS, full=False)


pytestmark = pytest.mark.slow   # generates four days of history and trains real models (several minutes)


@pytest.fixture(scope="session")
def history_and_emulator(campus):
    return emulated_history(campus, START, days=4)       # Monday 00:00 to Friday 00:00


@pytest.fixture(scope="session")
def history(history_and_emulator):
    return history_and_emulator[0]


@pytest.fixture(scope="session")
def trained(history):
    return train(history, FULL, train_fraction=0.7, max_train_samples=60_000, permutation_samples=2_000)


# ------------------------------------------------------------------ features
def test_feature_names_match_columns(history):
    X = build_features(fill_short_gaps(history.util), history.times, history.static, history.errors,
                       FULL, np.array([2000]))
    assert X.shape == (1, history.util.shape[1], len(FULL.names()))
    assert len(SHORT.names()) == len(FULL.names()) - 1 - 3 * len(HORIZONS)


def test_features_never_look_ahead(history):
    util = fill_short_gaps(history.util)
    row = np.array([3000])
    before = build_features(util, history.times, history.static, history.errors, FULL, row)
    future = util.copy()
    future[3001:] = 99.0                                # change everything after t
    after = build_features(future, history.times, history.static, history.errors, FULL, row)
    np.testing.assert_array_equal(np.nan_to_num(before), np.nan_to_num(after))


def test_online_and_offline_features_agree(history):
    """Serving computes features over a truncated buffer; training over the whole history."""
    util = fill_short_gaps(history.util)
    t = 2500
    offline = build_features(util, history.times, history.static, history.errors, FULL, np.array([t]))
    online = build_features(util[:t + 1], history.times[:t + 1], history.static, history.errors[:t + 1],
                            FULL, np.array([t]))
    np.testing.assert_allclose(np.nan_to_num(offline), np.nan_to_num(online), atol=1e-6)


def test_yesterday_is_the_previous_day_of_the_same_type():
    """Monday looks back to Friday and Saturday to the previous Sunday; with no such day, no seasonal change."""
    start = datetime.fromisoformat("2026-10-05T00:00:00+01:00").timestamp()       # Monday 00:00 WAT
    times = start + 60.0 * np.arange(8 * 1440)
    noon = [d * 1440 + 720 for d in (1, 5, 6, 7)]                                  # Tue, Sat, Sun, next Mon
    assert list(np.array(noon) - _reference_rows(times, np.array(noon), 1440)) == [1440, 6 * 1440, 1440, 3 * 1440]
    util = np.tile(np.linspace(10, 60, 1440, dtype=np.float32), 8)[:, None]
    X = build_features(util, times, np.zeros((1, 6), np.float32), None, FULL, np.array([5 * 1440 + 720]))[0, 0]
    names = FULL.names()
    assert X[names.index("yesterday_now")] == X[names.index("util_now")]           # first Saturday: no Sunday yet
    assert X[names.index("seasonal_gap_30")] == 0.0 and X[names.index("yesterday_change_30")] == 0.0


def test_rolling_and_slope_are_correct():
    values = np.arange(100, dtype=np.float32).reshape(-1, 1) * 2.0   # rises 2 points per cycle
    rows = np.array([50])
    mean, std, maximum = _rolling(values, rows, 5)
    assert mean[0, 0] == pytest.approx(np.mean(values[46:51]))
    assert std[0, 0] == pytest.approx(np.std(values[46:51]), rel=1e-5)
    assert maximum[0, 0] == pytest.approx(100.0)
    assert _slope(values, rows)[0, 0] == pytest.approx(2.0, rel=1e-5)


def test_short_gaps_are_filled_long_gaps_are_kept():
    values = np.array([[1.0], [np.nan], [np.nan], [4.0]] + [[np.nan]] * 8 + [[5.0]], dtype=np.float32)
    filled = fill_short_gaps(values, max_gap=5)
    assert filled[1, 0] == 1.0 and filled[2, 0] == 1.0
    assert np.isnan(filled[10, 0])                      # more than 5 missing cycles: left as a gap


def test_vectorised_gap_filling_matches_the_cycle_by_cycle_rule():
    """The engine fills gaps over a 7-day buffer every cycle, so it is vectorised; same result as a loop."""
    rng = np.random.default_rng(3)
    values = rng.uniform(0, 100, size=(2000, 7)).astype(np.float32)
    values[rng.random(values.shape) < 0.15] = np.nan                       # scattered misses
    for column in range(7):                                                # and some long outages
        start = rng.integers(0, 1900)
        values[start:start + rng.integers(1, 40), column] = np.nan
    values[:3, 0] = np.nan                                                 # nothing to carry forward yet

    expected = values.copy()
    for column in range(values.shape[1]):
        last, age = np.nan, 6
        for t in range(values.shape[0]):
            if np.isnan(values[t, column]):
                age += 1
                if age <= 5 and not np.isnan(last):
                    expected[t, column] = last
            else:
                last, age = values[t, column], 0
    np.testing.assert_array_equal(fill_short_gaps(values, max_gap=5), expected)


# ------------------------------------------------------------------ training
def test_training_reports_every_model_and_horizon(trained):
    assert set(trained.metrics) == {"random_forest", "gradient_boosting", "persistence", "linear_trend",
                                    "same_time_yesterday"}
    for results in trained.metrics.values():
        assert set(results) == {str(h) for h in HORIZONS}
    assert trained.sizes["random_forest_bytes"] < 100 * 1024 * 1024     # the plan's model-size cap
    assert sum(v for _, v in trained.importance) == pytest.approx(1.0, abs=1e-6)
    assert trained.classifier is not None
    assert trained.sizes["classifier_bytes"] < 100 * 1024 * 1024
    assert set(trained.classification) == {"random_forest_classifier", "regression_forecast", "linear_trend"}
    print("classification:", {k: {h: (round(v["precision"], 2), round(v["recall"], 2), v["positives"])
                                  for h, v in m.items()} for k, m in trained.classification.items()})


def test_forest_beats_naive_baselines_at_thirty_minutes(trained):
    forest = trained.metrics["random_forest"]["30"]["mae"]
    assert forest < trained.metrics["persistence"]["30"]["mae"]
    assert forest < trained.metrics["linear_trend"]["30"]["mae"]


# ------------------------------------------------------------------ registry
def test_registry_saves_loads_and_guards_promotion(trained, history, tmp_path):
    version = save(trained, tmp_path, history.link_ids, "full")
    assert promote(tmp_path, version)[0]
    loaded = load_active(tmp_path)["full"]
    assert loaded.spec == FULL and loaded.link_ids == history.link_ids
    # a model saved at the same moment gets its own folder
    worse = save(trained, tmp_path, history.link_ids, "full")
    assert worse != version
    # a deliberately worse model must not replace the active one
    meta_path = tmp_path / worse / "meta.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    for model in data["metrics"].values():
        for item in model.values():
            item["mae"] += 1000
    meta_path.write_text(json.dumps(data), encoding="utf-8")
    accepted, message = promote(tmp_path, worse)
    assert not accepted and "kept" in message
    assert load_active(tmp_path)["full"].version == version


# ------------------------------------------------------------------ serving
def test_history_buffer_keeps_time_alignment():
    buffer = HistoryBuffer([1, 2], 60, capacity=10)
    t0 = datetime(2026, 10, 5, tzinfo=UTC)
    buffer.append(t0, {1: 10.0, 2: 20.0}, {})
    buffer.append(t0 + timedelta(minutes=3), {1: 13.0}, {})       # two cycles missed
    times, util, _ = buffer.arrays()
    assert len(times) == 4 and np.isnan(util[1, 0]) and np.isnan(util[3, 1])
    assert not buffer.append(t0 + timedelta(minutes=3), {1: 99.0}, {})   # same cycle twice: ignored
    for k in range(20):
        buffer.append(t0 + timedelta(minutes=4 + k), {1: 1.0, 2: 2.0}, {})
    assert buffer.size == 10                                           # capacity respected


def test_predictor_forecasts_every_link_and_horizon(trained, history, tmp_path):
    version = save(trained, tmp_path, history.link_ids, "full")
    promote(tmp_path, version)
    predictor = Predictor(load_active(tmp_path), history.static, history.link_ids, critical_pct=90)
    buffer = HistoryBuffer(history.link_ids, 60, capacity=2 * 1440 + 60)
    for i in range(1500):
        moment = datetime.fromtimestamp(history.times[i], UTC)
        buffer.append(moment, dict(zip(history.link_ids, history.util[i].tolist(), strict=True)), {})
    rows = predictor.predict(buffer)
    assert len(rows) == len(history.link_ids) * len(HORIZONS)
    assert all(0.0 <= r.confidence_score <= 1.0 and 0.0 <= r.predicted_utilisation <= 100.0 for r in rows)
    # a warning is backed by the classifier's tuned threshold, or (critical now) by half the regression trees
    threshold = min(0.5, predictor.models["full"].classifier.threshold)
    assert all(r.confidence_score >= threshold for r in rows if r.is_warning)
    assert predictor.status(buffer)["model_kind"] == "full"


def test_predictor_waits_for_enough_history(trained, history, tmp_path):
    version = save(trained, tmp_path, history.link_ids, "full")
    promote(tmp_path, version)
    predictor = Predictor(load_active(tmp_path), history.static, history.link_ids, critical_pct=90)
    buffer = HistoryBuffer(history.link_ids, 60, capacity=100)
    buffer.append(datetime(2026, 10, 5, tzinfo=UTC), {1: 5.0}, {})
    assert predictor.predict(buffer) == []              # no short model and far too little history
    assert predictor.status(buffer)["active_model"] is None


def test_rising_link_is_flagged_at_least_ten_minutes_early(trained, history_and_emulator, tmp_path):
    """P3 exit criterion: a link ramping to congestion over about 20 minutes is warned >= 10 min early."""
    history, net = history_and_emulator
    version = save(trained, tmp_path, history.link_ids, "full")
    promote(tmp_path, version)
    predictor = Predictor(load_active(tmp_path), history.static, history.link_ids, critical_pct=90)
    buffer = HistoryBuffer(history.link_ids, 60, capacity=2 * 1440 + 60)
    for i in range(len(history.times)):
        buffer.append(datetime.fromtimestamp(history.times[i], UTC),
                      dict(zip(history.link_ids, history.util[i].tolist(), strict=True)), {})

    net.traffic.random_surges_enabled = False
    net.traffic.surges.clear()
    steps = net.steps_per_cycle()

    def advance_one_cycle():
        for _ in range(steps):
            net.step()
        cycle = net.truth[-1]
        moment = datetime.fromisoformat(cycle["end"]).astimezone(UTC)
        buffer.append(moment, {i + 1: lk["utilisation_pct"] for i, lk in enumerate(cycle["links"])}, {})
        return moment, cycle

    while datetime.fromisoformat(net.truth[-1]["end"]).astimezone(UTC).hour != 17 or \
            datetime.fromisoformat(net.truth[-1]["end"]).astimezone(UTC).minute != 30:   # Friday 18:30 WAT
        advance_one_cycle()
    target = net.find_link("DIST-HOSTEL", "AP-HOSTEL-01") + 1
    start_level = net.truth[-1]["links"][target - 1]["utilisation_pct"]
    net.add_surge("HOSTEL", "video", multiplier=2.3, ramp_minutes=20, hold_minutes=30)

    first_warning, onset, above = None, None, 0
    for _ in range(45):
        moment, cycle = advance_one_cycle()
        level = cycle["links"][target - 1]["utilisation_pct"]
        above = above + 1 if level >= 90 else 0
        if above == 2 and onset is None:
            onset = moment - timedelta(minutes=1)        # onset = first of two cycles at or above 90 %
        if first_warning is None and onset is None:
            rows = [r for r in predictor.predict(buffer) if r.link_id == target and r.is_warning]
            if rows:
                first_warning = moment
    print(f"start {start_level:.1f} %, onset {onset}, first warning {first_warning}")
    assert onset is not None, "the surge should congest the access point uplink"
    assert first_warning is not None, "no warning before congestion"
    assert (onset - first_warning) >= timedelta(minutes=10)


# ------------------------------------------------------------------ alerts
def forecasts(value: float, warn_at: int | None = None):
    return [Forecast(h, value if h != warn_at else 95.0, 0.9, h == warn_at) for h in HORIZONS]


def test_alert_episode_lifecycle_with_hysteresis():
    tracker = AlertTracker(critical_pct=90, clear_below_pct=85, clear_cycles=5)
    t0 = datetime(2026, 10, 5, 9, tzinfo=UTC)
    started, _ = tracker.update(t0, {7: forecasts(80, warn_at=15)}, {7: 75.0})
    assert len(started) == 1 and started[0].predicted_time == t0 + timedelta(minutes=15)
    # hovering just under the threshold (86-89 %) must not clear the alert
    for k in range(1, 10):
        _, ended = tracker.update(t0 + timedelta(minutes=k), {7: forecasts(88)}, {7: 80.0})
        assert not ended
    # five calm cycles below 85 % clear it
    for k in range(10, 15):
        _, ended = tracker.update(t0 + timedelta(minutes=k), {7: forecasts(60)}, {7: 50.0})
    assert len(ended) == 1 and 7 not in tracker.active


def test_replay_rebuilds_the_same_episodes():
    t0 = datetime(2026, 10, 5, 9, tzinfo=UTC)
    rows = []
    for k in range(30):
        value, warn = (95.0, True) if 5 <= k < 10 else (50.0, False)
        for h in HORIZONS:
            rows.append((3, t0 + timedelta(minutes=k), h, value, 0.8, warn))
    ended, active = replay(rows)
    assert len(ended) == 1 and not active
    assert ended[0].started_at == t0 + timedelta(minutes=5)
    assert ended[0].ended_at == t0 + timedelta(minutes=14)
