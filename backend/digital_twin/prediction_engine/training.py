"""Train and evaluate the forecasting models on twin-collected history (plan section 7.5, evaluation E2).

The split is by time: the first part trains, the rest tests. Training rows stop
short of the split by the longest horizon, so no test-period value ever leaks
into training. Two Random Forests are trained:

* the regression forest forecasts utilisation at each horizon (compared with
  gradient boosting and three baselines);
* the classification forest predicts whether the link will reach the critical
  threshold within each horizon (it makes the warnings). Its warning threshold is
  chosen on a validation slice, the last 20 % of the TRAINING period (a classifier
  fitted on the first 80 % is scored there), never on the test period.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from sklearn.inspection import permutation_importance
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from .features import (
    FeatureSpec,
    build_crossing_labels,
    build_features,
    build_targets,
    fill_short_gaps,
)
from .models import BoostingForecaster, CongestionClassifier, ForestForecaster, baseline_predictions

VALIDATION_FRACTION = 0.2                              # end of the training period used to choose the threshold
THRESHOLDS = np.round(np.arange(0.05, 0.96, 0.05), 2)  # candidate warning probabilities


@dataclass
class History:
    """Time-aligned history: one row per cycle (oldest first), one column per link."""

    times: np.ndarray          # (T,) epoch seconds
    util: np.ndarray           # (T, L) utilisation %, NaN for gaps
    errors: np.ndarray | None  # (T, L) error counts per cycle
    static: np.ndarray         # (L, S) from features.static_features
    link_ids: list[int]
    cycle_seconds: int


@dataclass
class TrainResult:
    spec: FeatureSpec
    forest: ForestForecaster
    boosting: BoostingForecaster | None
    classifier: CongestionClassifier | None
    metrics: dict
    classification: dict
    importance: list[tuple[str, float]]
    permutation: list[tuple[str, float]]
    rows: dict
    seconds: dict
    sizes: dict
    window: dict = field(default_factory=dict)


def matrices(history: History, spec: FeatureSpec, rows: np.ndarray,
             critical: float = 90.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flattened features (samples, F), utilisation targets (samples, H) and crossing labels (samples, H).

    Samples with a missing current value or missing targets are dropped."""
    util = fill_short_gaps(history.util)
    X = build_features(util, history.times, history.static, history.errors, spec, rows)
    Y = build_targets(history.util, rows, spec)       # targets use the raw (unfilled) values
    C = build_crossing_labels(history.util, rows, spec, critical)
    X = X.reshape(-1, X.shape[2])
    Y = Y.reshape(-1, Y.shape[2])
    C = C.reshape(-1, C.shape[2])
    keep = ~np.isnan(Y).any(axis=1) & ~np.isnan(X[:, 0]) & ~np.isnan(C).any(axis=1)
    return X[keep], Y[keep], C[keep]


def metrics(y_true: np.ndarray, y_pred: np.ndarray, horizons: tuple[int, ...]) -> dict:
    out = {}
    for j, h in enumerate(horizons):
        t, p = y_true[:, j], y_pred[:, j]
        err = p - t
        busy = t >= 10.0
        high = t >= 70.0
        ss_res = float((err ** 2).sum())
        ss_tot = float(((t - t.mean()) ** 2).sum()) or 1.0
        out[str(h)] = {
            "mae": float(np.abs(err).mean()),
            "rmse": float(np.sqrt((err ** 2).mean())),
            "mape_busy": float((np.abs(err[busy]) / t[busy]).mean() * 100) if busy.any() else None,
            "smape": float((2 * np.abs(err) / np.maximum(np.abs(t) + np.abs(p), 1e-6)).mean() * 100),
            "r2": 1.0 - ss_res / ss_tot,
            "mae_high": float(np.abs(err[high]).mean()) if high.any() else None,
            "samples": int(len(t)),
            "samples_high": int(high.sum()),
        }
    return out


def classification_metrics(labels: np.ndarray, probability: np.ndarray, horizons: tuple[int, ...],
                           threshold: float = 0.5) -> dict:
    out = {}
    for j, h in enumerate(horizons):
        y, p = labels[:, j].astype(int), probability[:, j]
        predicted = (p >= threshold).astype(int)
        both = len(set(y.tolist())) == 2
        out[str(h)] = {
            "positives": int(y.sum()),
            "samples": int(len(y)),
            "precision": float(precision_score(y, predicted, zero_division=0)),
            "recall": float(recall_score(y, predicted, zero_division=0)),
            "f1": float(f1_score(y, predicted, zero_division=0)),
            "roc_auc": float(roc_auc_score(y, p)) if both else None,
        }
    return out


def choose_threshold(labels: np.ndarray, probability: np.ndarray) -> float:
    """The candidate probability with the best F1 averaged over the horizons (ties: the lowest)."""
    scores = [np.mean([f1_score(labels[:, j].astype(int), (probability[:, j] >= t).astype(int), zero_division=0)
                       for j in range(labels.shape[1])]) for t in THRESHOLDS]
    return float(THRESHOLDS[int(np.argmax(scores))])


def _limit(X: np.ndarray, Y: np.ndarray, C: np.ndarray, max_samples: int, rng: np.random.Generator):
    """Keep every sample that leads to congestion (rare and important), sample the rest."""
    if len(X) <= max_samples:
        return X, Y, C
    rising = np.flatnonzero(C.any(axis=1))
    others = np.setdiff1d(np.arange(len(X)), rising)
    keep = max(0, max_samples - len(rising))
    pick = np.concatenate([rising, rng.choice(others, min(keep, len(others)), replace=False)])
    return X[pick], Y[pick], C[pick]


def validated_threshold(history: History, spec: FeatureSpec, train_rows: np.ndarray, critical: float,
                        columns: int | None, max_samples: int, rng: np.random.Generator) -> float:
    """Fit a classifier on the first 80 % of the training rows and choose the threshold on the last 20 %.
    Rows within the longest horizon of the cut are dropped, so no validation value is a training target."""
    cut = train_rows[0] + int((train_rows[-1] - train_rows[0]) * (1 - VALIDATION_FRACTION))
    fit_rows = train_rows[train_rows < cut - max(spec.horizon_steps)]
    val_rows = train_rows[train_rows >= cut]
    X_fit, Y_fit, C_fit = _limit(*matrices(history, spec, fit_rows, critical), max_samples, rng)
    X_val, _, C_val = matrices(history, spec, val_rows, critical)
    fit_below, val_below = X_fit[:, 0] < critical, X_val[:, 0] < critical
    if not (C_fit[fit_below].any() and C_val[val_below].any()):
        return 0.5                                   # no congestion on one side of the cut: keep the default
    model = CongestionClassifier(columns=columns).fit(X_fit[fit_below], C_fit[fit_below])
    return choose_threshold(C_val[val_below], model.probability(X_val[val_below]))


def split_rows(history: History, spec: FeatureSpec, train_fraction: float, train_stride: int,
               test_stride: int) -> tuple[np.ndarray, np.ndarray]:
    total = len(history.times)
    first = spec.needed_history
    longest = max(spec.horizon_steps)
    last = total - longest - 1
    if last - first < 200:
        raise ValueError(f"not enough history: {total} cycles, need at least {first + longest + 200}")
    split = first + int((last - first) * train_fraction)
    train = np.arange(first, split - longest, train_stride)    # targets end before the split: no leakage
    test = np.arange(split, last + 1, test_stride)
    return train, test


def train(history: History, spec: FeatureSpec, *, critical_pct: float = 90.0, train_fraction: float = 10 / 14,
          train_stride: int = 3, test_stride: int = 2, max_train_samples: int = 200_000,
          with_boosting: bool = True, with_classifier: bool = True, permutation_samples: int = 20_000,
          seed: int = 7) -> TrainResult:
    rng = np.random.default_rng(seed)
    train_rows, test_rows = split_rows(history, spec, train_fraction, train_stride, test_stride)
    t0 = time.perf_counter()
    X_train, Y_train, C_train = matrices(history, spec, train_rows, critical_pct)
    X_test, Y_test, C_test = matrices(history, spec, test_rows, critical_pct)
    X_train, Y_train, C_train = _limit(X_train, Y_train, C_train, max_train_samples, rng)
    t1 = time.perf_counter()
    forest = ForestForecaster().fit(X_train, Y_train)
    t2 = time.perf_counter()
    boosting = BoostingForecaster().fit(X_train, Y_train) if with_boosting else None
    t3 = time.perf_counter()
    classifier = None
    below = X_train[:, 0] < critical_pct          # warnings are about links not yet critical
    if with_classifier and C_train[below].any():
        columns = len(FeatureSpec(spec.cycle_seconds, spec.horizons_minutes, full=False).names())
        classifier = CongestionClassifier(columns=columns).fit(X_train[below], C_train[below])
        classifier.threshold = validated_threshold(history, spec, train_rows, critical_pct, columns,
                                                   max_train_samples, rng)
    t4 = time.perf_counter()

    horizons = spec.horizons_minutes
    results = {"random_forest": metrics(Y_test, forest.predict(X_test), horizons)}
    if boosting:
        results["gradient_boosting"] = metrics(Y_test, boosting.predict(X_test), horizons)
    for name, pred in baseline_predictions(X_test, spec).items():
        results[name] = metrics(Y_test, pred, horizons)
    test_below = X_test[:, 0] < critical_pct
    classification = {}
    if classifier is not None:
        classification["random_forest_classifier"] = classification_metrics(
            C_test[test_below], classifier.probability(X_test[test_below]), horizons, classifier.threshold)
    # for comparison: warn when the regression forecast itself reaches the threshold
    classification["regression_forecast"] = classification_metrics(
        C_test[test_below], (forest.predict(X_test[test_below]) >= critical_pct).astype(float), horizons)
    trend = baseline_predictions(X_test[test_below], spec)["linear_trend"]
    classification["linear_trend"] = classification_metrics(
        C_test[test_below], (trend >= critical_pct).astype(float), horizons)
    t5 = time.perf_counter()

    names = spec.names()
    importance = sorted(zip(names, map(float, forest.feature_importances()), strict=True), key=lambda x: -x[1])
    permutation: list[tuple[str, float]] = []
    if permutation_samples:
        pick = rng.choice(len(X_test), min(permutation_samples, len(X_test)), replace=False)
        perm = permutation_importance(forest.model, X_test[pick], Y_test[pick] - X_test[pick, :1], n_repeats=2,
                                      scoring="neg_mean_absolute_error", random_state=seed, n_jobs=1)
        permutation = sorted(zip(names, map(float, perm.importances_mean), strict=True), key=lambda x: -x[1])
    t6 = time.perf_counter()

    return TrainResult(
        spec=spec, forest=forest, boosting=boosting, classifier=classifier, metrics=results,
        classification=classification, importance=importance, permutation=permutation,
        rows={"train_samples": int(len(X_train)), "test_samples": int(len(X_test)),
              "train_congestion_samples": int(C_train.any(axis=1).sum()),
              "test_congestion_samples": int(C_test.any(axis=1).sum()),
              "warning_threshold": classifier.threshold if classifier is not None else None,
              "links": len(history.link_ids), "history_cycles": int(len(history.times))},
        seconds={"features": round(t1 - t0, 2), "random_forest": round(t2 - t1, 2),
                 "gradient_boosting": round(t3 - t2, 2), "classifier": round(t4 - t3, 2),
                 "evaluation": round(t5 - t4, 2), "permutation": round(t6 - t5, 2)},
        sizes={"random_forest_bytes": forest.size_bytes(),
               "gradient_boosting_bytes": boosting.size_bytes() if boosting else 0,
               "classifier_bytes": classifier.size_bytes() if classifier else 0},
        window={"train_start": float(history.times[train_rows[0]]), "train_end": float(history.times[train_rows[-1]]),
                "test_start": float(history.times[test_rows[0]]), "test_end": float(history.times[test_rows[-1]])},
    )
