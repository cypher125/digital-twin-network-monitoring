"""Forecasting models (Figures 3.1/3.2: scikit-learn Random Forest; Table 3.5: compared with gradient boosting).

* ForestForecaster: the production model, one multi-output Random Forest for all
  horizons, with fixed size limits so it fits in 4 GB RAM (plan section 7.5).
  Confidence (D5) = share of trees that agree with the verdict.
* BoostingForecaster: HistGradientBoostingRegressor, one per horizon, for comparison.
* Baselines: persistence, same time yesterday, linear trend.

Both regression models predict the CHANGE from now, u(t+h) - u(t), and add it to the
current utilisation. A tree can only output averages of what it saw in training;
predicting the change lets a forecast go above any level seen before.

* CongestionClassifier: a Random Forest CLASSIFIER answering "will this link reach the
  critical threshold within h minutes?" for each horizon. Regression minimises the
  average error, and in normal traffic a sudden slope is usually noise that reverts,
  so a regressor learns to distrust slopes and reacts late to a real ramp. Warnings
  are a classification question, so a classifier makes them (as in the classification
  approaches to performance-degradation prediction reviewed by Ahmed et al. 2016).
  Its probability, the share of its trees voting "congestion", is the confidence (D5).
  It is trained without class weights, so that probability stays close to how often
  similar past situations really congested; congestion is rare, so the warning
  threshold is chosen on a validation slice instead (training.train). It uses only the
  short-history features: flash crowds start at random times, so the same-time-yesterday
  values say nothing about them and only add noise from too few congestion examples.
"""
from __future__ import annotations

import pickle

import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)

from .features import FeatureSpec

RF_PARAMS = {
    "n_estimators": 100,
    "max_depth": 14,
    "min_samples_leaf": 15,   # small enough for rare ramp states to get their own leaves
    "max_samples": 0.2,       # each tree sees 20 % of the rows: bounds memory and model size
    "max_features": 0.5,
    "n_jobs": 2,
    "random_state": 7,
}
HGB_PARAMS = {
    "max_iter": 250,
    "learning_rate": 0.06,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 20,
    "random_state": 7,
}
CLF_PARAMS = {
    "n_estimators": 100,
    "max_depth": 12,
    "min_samples_leaf": 5,
    "max_samples": 0.3,
    "max_features": 0.5,
    "class_weight": None,     # no re-weighting: rarity is handled by the tuned warning threshold
    "n_jobs": 2,
    "random_state": 7,
}


NOW = 0  # column of the current utilisation in the feature matrix (features.FeatureSpec.names)


def _clip(values: np.ndarray) -> np.ndarray:
    return np.clip(values, 0.0, 100.0)


def _now(X: np.ndarray) -> np.ndarray:
    return X[:, NOW:NOW + 1]


class ForestForecaster:
    kind = "random_forest"

    def __init__(self, **params):
        self.model = RandomForestRegressor(**{**RF_PARAMS, **params})

    def fit(self, X: np.ndarray, Y: np.ndarray) -> ForestForecaster:
        self.model.fit(X, Y - _now(X))          # learn the change from now
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return _clip(_now(X) + np.asarray(self.model.predict(X)).reshape(len(X), -1))

    def tree_predictions(self, X: np.ndarray) -> np.ndarray:
        """(n_trees, n, H) forecasts of the individual trees (current utilisation + predicted change)."""
        return _now(X)[None] + np.stack([np.asarray(t.predict(X)).reshape(len(X), -1)
                                         for t in self.model.estimators_])

    def predict_with_confidence(self, X: np.ndarray, critical: float) -> tuple[np.ndarray, np.ndarray]:
        trees = self.tree_predictions(X)
        mean = _clip(trees.mean(axis=0))
        share_critical = (trees >= critical).mean(axis=0)
        confidence = np.where(mean >= critical, share_critical, 1.0 - share_critical)
        return mean, confidence

    def feature_importances(self) -> np.ndarray:
        return self.model.feature_importances_

    def size_bytes(self) -> int:
        return len(pickle.dumps(self.model, protocol=pickle.HIGHEST_PROTOCOL))


class BoostingForecaster:
    kind = "gradient_boosting"

    def __init__(self, **params):
        self.params = {**HGB_PARAMS, **params}
        self.models: list[HistGradientBoostingRegressor] = []

    def fit(self, X: np.ndarray, Y: np.ndarray) -> BoostingForecaster:
        delta = Y - _now(X)
        self.models = [HistGradientBoostingRegressor(**self.params).fit(X, delta[:, j]) for j in range(Y.shape[1])]
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return _clip(_now(X) + np.stack([m.predict(X) for m in self.models], axis=1))

    def size_bytes(self) -> int:
        return len(pickle.dumps(self.models, protocol=pickle.HIGHEST_PROTOCOL))


class CongestionClassifier:
    """P(link reaches the critical threshold within h minutes), one output per horizon."""

    kind = "random_forest_classifier"

    def __init__(self, columns: int | None = None, **params):
        self.model = RandomForestClassifier(**{**CLF_PARAMS, **params})
        self.horizons = 0
        self.columns = columns    # use only the first `columns` features (the short-history set)
        self.threshold = 0.5      # warning probability; training.train tunes it on a validation slice

    def _features(self, X: np.ndarray) -> np.ndarray:
        columns = getattr(self, "columns", None)          # models saved before this attribute existed: all
        return X if columns is None else X[:, :columns]

    def fit(self, X: np.ndarray, labels: np.ndarray) -> CongestionClassifier:
        self.horizons = labels.shape[1]
        self.model.fit(self._features(X), labels.astype(np.int8))
        return self

    def probability(self, X: np.ndarray) -> np.ndarray:
        """(n, H) probability of congestion; a horizon never congested in training gets 0."""
        raw = self.model.predict_proba(self._features(X))
        raw = raw if isinstance(raw, list) else [raw]
        out = np.zeros((len(X), self.horizons))
        for j, (proba, classes) in enumerate(zip(raw, self.model.classes_, strict=True)):
            if 1 in list(classes):
                out[:, j] = proba[:, list(classes).index(1)]
        return out

    def size_bytes(self) -> int:
        return len(pickle.dumps(self.model, protocol=pickle.HIGHEST_PROTOCOL))


def baseline_predictions(X: np.ndarray, spec: FeatureSpec) -> dict[str, np.ndarray]:
    """The three baselines, computed from the same feature matrix."""
    names = spec.names()
    now = X[:, names.index("util_now")]
    slope = np.nan_to_num(X[:, names.index("slope_15")], nan=0.0)   # the classic 15-minute trend line
    steps = np.array(spec.horizon_steps, dtype=np.float32)
    out = {
        "persistence": np.repeat(now[:, None], len(steps), axis=1),
        "linear_trend": _clip(now[:, None] + slope[:, None] * steps[None, :]),
    }
    if spec.full:
        cols = [names.index(f"yesterday_plus_{h}") for h in spec.horizons_minutes]
        yesterday = X[:, cols]
        out["same_time_yesterday"] = np.where(np.isnan(yesterday), now[:, None], yesterday)
    return out
