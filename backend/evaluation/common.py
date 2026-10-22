"""Shared helpers for the evaluation experiments E1-E9 (plan section 11).

Every experiment writes its evidence to backend/evaluation/results/<ID>/:
    results.json   headline figures + the configuration that produced them
    *.csv          the full numbers behind every chart (the chart's table view)
    *.png          charts for Chapter 4

Charts follow the dashboard's data-visualisation rules, for print: one y-axis, 2 px lines,
hairline solid grid, dashed lines only for thresholds and forecasts, a legend whenever there
are two or more series, text in ink colours (never the series colour), at most three
categorical colours per chart (validated for colour-blind separation), status colours only
for the 70 % / 90 % thresholds.
"""
from __future__ import annotations

import csv
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
RESULTS = BACKEND / "evaluation" / "results"

# reference palette (light print surface); slots 1-3 pass the all-pairs colour-blind checks
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             check=False, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True,
                               check=False, timeout=10).stdout.strip()
        return out.stdout.strip() + ("+uncommitted" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


@dataclass
class Results:
    """One experiment's output folder and its running summary."""

    experiment: str                       # e.g. "E1"
    title: str
    config: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    started: float = field(default_factory=time.time)

    @property
    def folder(self) -> Path:
        path = RESULTS / self.experiment
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(self, name: str, payload) -> Path:
        path = self.folder / name
        path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
        return path

    def write_csv(self, name: str, rows: list[dict], fields: list[str] | None = None) -> Path:
        path = self.folder / name
        fields = fields or (list(rows[0]) if rows else [])
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _csv_value(row.get(k)) for k in fields})
        return path

    def save_chart(self, figure, name: str) -> Path:
        path = self.folder / name
        figure.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
        import matplotlib.pyplot as plt
        plt.close(figure)
        return path

    def finish(self) -> Path:
        """Write results.json with the summary, configuration and provenance."""
        payload = {
            "experiment": self.experiment,
            "title": self.title,
            "finished": datetime.now(UTC).isoformat(timespec="seconds"),
            "seconds": round(time.time() - self.started, 1),
            "code_version": git_commit(),
            "python": sys.version.split()[0],
            "machine": f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}",
            "config": self.config,
            "summary": self.summary,
        }
        return self.write_json("results.json", payload)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):           # NumPy scalars
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def _csv_value(value):
    if isinstance(value, float):
        return round(value, 6)
    if hasattr(value, "item"):
        return value.item()
    return value


# ---------------------------------------------------------------- charts
def chart(width: float = 7.5, height: float = 3.4):
    """A figure and axes in the house style. Returns (figure, axes).

    No title inside the image: Chapter 4 gives every figure a numbered caption."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
        "font.size": 9,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "axes.facecolor": SURFACE,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "grid.linestyle": "-",
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": MUTED,
        "ytick.labelcolor": MUTED,
        "lines.linewidth": 2.0,
        "lines.solid_capstyle": "round",
        "legend.frameon": False,
        "legend.labelcolor": INK_2,
        "figure.facecolor": "white",
    })
    return plt.subplots(figsize=(width, height))


def threshold_lines(axes, warning: float = 70.0, critical: float = 90.0, orientation: str = "h") -> None:
    """The 70 % warning and 90 % critical thresholds: dashed, in the status colours, labelled in ink."""
    draw = axes.axhline if orientation == "h" else axes.axvline
    for value, colour, label in ((warning, STATUS["warning"], f"Warning {warning:g}%"),
                                 (critical, STATUS["critical"], f"Critical {critical:g}%")):
        draw(value, color=colour, linestyle=(0, (4, 3)), linewidth=1.3, label=label, zorder=1)


def legend(axes, **kwargs) -> None:
    """Legend above the plot, left-aligned (only call it for two or more series)."""
    axes.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=kwargs.pop("ncol", 4), fontsize=8.5,
                handlelength=1.8, borderaxespad=0.2, **kwargs)
