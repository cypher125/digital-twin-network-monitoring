"""Model registry: trained models on disk with their metadata (plan section 7.5).

    var/models/<version>/model.joblib   the fitted forecasters and feature spec
    var/models/<version>/meta.json      training window, rows, metrics, importance, sizes, library versions
    var/models/active.json              which version serves as the "full" and the "short" model

A new model is promoted only if its Random Forest test error is no worse than the
model it replaces.
"""
from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import sklearn

from .features import FeatureSpec
from .models import CongestionClassifier, ForestForecaster
from .training import TrainResult


@dataclass
class LoadedModel:
    version: str
    kind: str                 # "full" or "short"
    spec: FeatureSpec
    forest: ForestForecaster
    link_ids: list[int]
    meta: dict
    classifier: CongestionClassifier | None = None


def mean_mae(metrics: dict, model: str = "random_forest") -> float:
    return float(np.mean([m["mae"] for m in metrics[model].values()]))


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def save(result: TrainResult, model_dir: str | Path, link_ids: list[int], kind: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    version = f"rf-{kind}-{stamp}"
    folder = Path(model_dir) / version
    suffix = 1
    while folder.exists():  # never overwrite an existing model, even if saved in the same instant
        folder = Path(model_dir) / f"{version}-{suffix}"
        suffix += 1
    version = folder.name
    folder.mkdir(parents=True)
    joblib.dump({"spec": result.spec, "forest": result.forest, "classifier": result.classifier,
                 "link_ids": link_ids}, folder / "model.joblib", compress=3)
    meta = {
        "version": version,
        "kind": kind,
        "created_at": datetime.now(UTC).isoformat(),
        "spec": asdict(result.spec),
        "feature_names": result.spec.names(),
        "metrics": result.metrics,
        "classification": result.classification,
        "importance": result.importance,
        "permutation_importance": result.permutation,
        "rows": result.rows,
        "seconds": result.seconds,
        "sizes": {**result.sizes, "file_bytes": (folder / "model.joblib").stat().st_size},
        "window": {k: datetime.fromtimestamp(v, UTC).isoformat() for k, v in result.window.items()},
        "libraries": {"scikit-learn": sklearn.__version__, "numpy": np.__version__,
                      "python": platform.python_version()},
    }
    _write_json(folder / "meta.json", meta)
    return version


def read_active(model_dir: str | Path) -> dict:
    path = Path(model_dir) / "active.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def promote(model_dir: str | Path, version: str, *, force: bool = False) -> tuple[bool, str]:
    """Make `version` active for its kind, unless it is worse than the current one."""
    model_dir = Path(model_dir)
    meta = json.loads((model_dir / version / "meta.json").read_text(encoding="utf-8"))
    kind = meta["kind"]
    active = read_active(model_dir)
    current = active.get(kind)
    if current and not force and (model_dir / current / "meta.json").exists():
        old = json.loads((model_dir / current / "meta.json").read_text(encoding="utf-8"))
        new_mae, old_mae = mean_mae(meta["metrics"]), mean_mae(old["metrics"])
        if new_mae > old_mae:
            return False, f"kept {current}: its test MAE {old_mae:.3f} is better than {new_mae:.3f}"
    active[kind] = version
    _write_json(model_dir / "active.json", active)
    return True, f"{version} is now the active {kind} model"


def load(model_dir: str | Path, version: str) -> LoadedModel:
    folder = Path(model_dir) / version
    bundle = joblib.load(folder / "model.joblib")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    return LoadedModel(version, meta["kind"], bundle["spec"], bundle["forest"], bundle["link_ids"], meta,
                       bundle.get("classifier"))


def load_active(model_dir: str | Path) -> dict[str, LoadedModel]:
    return {kind: load(model_dir, version) for kind, version in read_active(model_dir).items()
            if (Path(model_dir) / version / "model.joblib").exists()}
