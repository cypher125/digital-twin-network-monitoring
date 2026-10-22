"""E7 Deployable on modest hardware (gap G4) and scalability.

Method, in four parts (choose with --parts; all by default):

steady    With the whole system running as deployed (deploy/start.ps1), every 5 s for
          10 minutes: CPU (% of one core) and resident memory of each service, counting its
          whole process tree (psutil). Compared with the plan's budgets (section 12.1):
          engine <= 300 MB, API <= 150 MB, emulator <= 150 MB; and the total with the 4 GB laptop.
database  Size of the database and of each table, bytes per stored row, rows written per
          day of network time (77 monitoring records and 172 forecasts per cycle), and the
          storage the retention rules settle at (14 days of measurements, 2 days of forecasts).
          Round-trip time of a trivial query (median of 20) shows the cost of a remote database.
api       Response times while 1, 3 and 5 dashboards are open at once: each simulated
          dashboard polls `live` every second and, when the twin stores a new cycle, fetches
          `topology` and `alerts/active`, as the real dashboard does (D28). Median and 95th
          percentile per endpoint.
scale     The same software on bigger campuses: synthetic topologies of about 40, 100 and 200
          devices, made by copying the hostel zone (one distribution switch, one access switch,
          two Wi-Fi access points) as new zones. For each: time to ingest one monitoring cycle
          (collect, validate, update the model), to run a link-failure simulation, to forecast
          every link once (the trained Random Forest, which works per link), and to draw the
          network map in a browser (Cytoscape.js in headless Edge, first frame).

Target (plan): runs within 4 GB of RAM. Limitations: one laptop (Intel Celeron N4020, 2 cores);
the synthetic campuses copy one zone, so their traffic pattern is regular.

    set DT_SENIOR=senior1:password
    python -m evaluation.e7_resources [--parts steady,database,api,scale] [--quick]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import subprocess
import threading
import time
from datetime import datetime

import numpy as np

from .common import BACKEND, ROOT, SERIES, Results, chart, legend
from .system import Dashboard, ResourceSampler, service_pids

BUDGETS_MB = {"engine": 300, "api": 150, "emulator": 150}
CAMPUS = ROOT / "data" / "topologies" / "campus.yaml"


# ------------------------------------------------------------------ steady
def steady(results: Results, minutes: float) -> dict:
    if not service_pids():
        return {"skipped": "the system is not running (start it with deploy/start.ps1)"}
    sampler = ResourceSampler()
    sampler.sample()
    rows = []
    end = time.monotonic() + minutes * 60
    while time.monotonic() < end:
        time.sleep(5)
        for name, info in sampler.sample().items():
            rows.append({"t": datetime.now().isoformat(timespec="seconds"), "service": name, **info})
    results.write_csv("steady.csv", rows, ["t", "service", "pid", "cpu_pct", "rss_mb", "processes"])
    out = {}
    for name in sorted({r["service"] for r in rows}):
        rss = np.array([r["rss_mb"] for r in rows if r["service"] == name])
        cpu = np.array([r["cpu_pct"] for r in rows if r["service"] == name])
        out[name] = {"rss_mean_mb": round(float(rss.mean()), 1), "rss_max_mb": round(float(rss.max()), 1),
                     "cpu_mean_pct": round(float(cpu.mean()), 1), "cpu_p95_pct": round(float(np.percentile(cpu, 95)), 1),
                     "budget_mb": BUDGETS_MB.get(name),
                     "within_budget": None if name not in BUDGETS_MB else bool(rss.max() <= BUDGETS_MB[name])}
    total = sum(v["rss_max_mb"] for v in out.values())
    import psutil
    memory = psutil.virtual_memory()
    figure, axes = chart(6.5, 3.0)
    names = sorted(out)
    axes.barh(names, [out[n]["rss_max_mb"] for n in names], height=0.5, color=SERIES[0], label="Peak memory")
    for i, name in enumerate(names):
        axes.text(out[name]["rss_max_mb"] + 4, i, f"{out[name]['rss_max_mb']:.0f} MB", va="center", fontsize=8)
        if out[name]["budget_mb"]:
            axes.plot([out[name]["budget_mb"]] * 2, [i - 0.35, i + 0.35], color=SERIES[1], linewidth=2)
    axes.plot([], [], color=SERIES[1], linewidth=2, label="Budget (plan 12.1)")
    axes.set_xlabel("Resident memory, whole process tree (MB)")
    axes.grid(axis="x")
    axes.grid(axis="y", visible=False)
    legend(axes, ncol=2)
    results.save_chart(figure, "memory_by_service.png")
    return {"services": out, "total_peak_mb": round(total, 1), "laptop_total_mb": round(memory.total / 1e6),
            "minutes": minutes}


# ------------------------------------------------------------------ database
def database() -> dict:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django
    django.setup()
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        server = cursor.fetchone()[0].split(" on ")[0]
        cursor.execute("SELECT pg_database_size(current_database())")
        total = cursor.fetchone()[0]
        tables = {}
        for table in ("monitoring_record", "prediction", "simulation_scenario", "simulation_result", "network_device",
                      "network_link"):
            cursor.execute("SELECT pg_total_relation_size(%s), (SELECT count(*) FROM " + table + ")", [table])
            size, rows = cursor.fetchone()
            tables[table] = {"bytes": size, "rows": rows, "bytes_per_row": round(size / rows, 1) if rows else None}
        rtts = []
        for _ in range(20):
            began = time.perf_counter()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            rtts.append((time.perf_counter() - began) * 1000)
    host = connection.settings_dict.get("HOST")
    per_cycle = {"monitoring_record": 77, "prediction": 172}        # 43 links + 34 devices; 43 links x 4 horizons
    per_day = {k: v * 1440 for k, v in per_cycle.items()}
    retained = {"monitoring_record": per_day["monitoring_record"] * 14, "prediction": per_day["prediction"] * 2}
    steady_bytes = sum(retained[k] * (tables[k]["bytes_per_row"] or 0) for k in retained)
    return {"server": server, "host": "local" if host in ("127.0.0.1", "localhost") else host,
            "database_bytes": total, "tables": tables, "rows_per_day_network_time": per_day,
            "rows_at_retention": retained, "storage_at_retention_mb": round(steady_bytes / 1e6, 1),
            "query_round_trip_ms_median": round(statistics.median(rtts), 2), "query_round_trip_ms_max": round(max(rtts), 2)}


# ------------------------------------------------------------------ api
def api_load(results: Results, url: str, levels: list[int], seconds: float) -> dict:
    out, rows = {}, []
    for dashboards in levels:
        lock = threading.Lock()
        samples: dict[str, list[float]] = {"live": [], "topology": [], "alerts/active": []}
        failures = {"count": 0}
        stop_at = time.monotonic() + seconds

        def run_one(stop_at=stop_at, lock=lock, samples=samples, failures=failures):
            client = Dashboard(url)
            client.sign_in()
            version = None
            while time.monotonic() < stop_at:
                tick = time.monotonic()
                took, ok = client.timed_get("live")
                live = client.get("live") if ok else None
                with lock:
                    samples["live"].append(took)
                    failures["count"] += 0 if ok else 1
                if live and live.get("state_version") != version:
                    version = live.get("state_version")
                    for path in ("topology", "alerts/active"):
                        took, ok = client.timed_get(path)
                        with lock:
                            samples[path].append(took)
                            failures["count"] += 0 if ok else 1
                time.sleep(max(0.0, 1.0 - (time.monotonic() - tick)))

        threads = [threading.Thread(target=run_one) for _ in range(dashboards)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        out[str(dashboards)] = {}
        for path, values in samples.items():
            if values:
                ms = np.array(values) * 1000
                out[str(dashboards)][path] = {"requests": len(values), "p50_ms": round(float(np.median(ms)), 1),
                                              "p95_ms": round(float(np.percentile(ms, 95)), 1),
                                              "max_ms": round(float(ms.max()), 1)}
                rows.append({"dashboards": dashboards, "endpoint": path, **out[str(dashboards)][path]})
        out[str(dashboards)]["failures"] = failures["count"]
    results.write_csv("api_latency.csv", rows, ["dashboards", "endpoint", "requests", "p50_ms", "p95_ms", "max_ms"])
    figure, axes = chart(6.5, 3.0)
    for index, path in enumerate(["live", "topology", "alerts/active"]):
        xs = [lvl for lvl in levels if path in out[str(lvl)]]
        axes.plot(xs, [out[str(x)][path]["p95_ms"] for x in xs], marker="o", markersize=5, color=SERIES[index],
                  markeredgecolor="white", label=f"{path} (95th percentile)")
    axes.set_xticks(levels)
    axes.set_xlabel("Dashboards open at once")
    axes.set_ylabel("Response time (ms)")
    axes.set_ylim(bottom=0)
    legend(axes, ncol=3)
    results.save_chart(figure, "api_latency.png")
    return {"seconds_per_level": seconds, "levels": out}


# ------------------------------------------------------------------ scale
def synthetic_topology(raw: dict, extra_zones: int) -> dict:
    """The campus plus `extra_zones` copies of the hostel zone (4 devices, 5 links each)."""
    raw = copy.deepcopy(raw)
    hostel = raw["zones"]["HOSTEL"]
    for i in range(1, extra_zones + 1):
        zone = f"Z{i:02d}"
        names = {"DIST-HOSTEL": f"DIST-{zone}", "ACC-HOSTEL-01": f"ACC-{zone}-01", "AP-HOSTEL-01": f"AP-{zone}-01",
                 "AP-HOSTEL-02": f"AP-{zone}-02"}
        for device in [d for d in raw["devices"] if d["name"] in names]:
            clone = {**device, "name": names[device["name"]], "zone": zone, "ip": f"10.{100 + i}.0.{len(names)}",
                     "position": [60 + 80 * ((i - 1) % 15), 760 + 140 * ((i - 1) // 15) + (60 if "AP" in device["name"] else 0)]}
            raw["devices"].append(clone)
        for link in [lk for lk in raw["links"] if lk[0] in names or lk[1] in names]:
            if lk_has(link, "DIST-HOSTEL"):
                raw["links"].append([names.get(link[0], link[0]), names.get(link[1], link[1]), *link[2:]])
        raw["zones"][zone] = {**hostel, "name": f"Residence {i}", "population": 300,
                              "access": {names[k]: v for k, v in hostel["access"].items()}}
    return raw


def lk_has(link: list, name: str) -> bool:
    return link[0] == name or link[1] == name


def scale(results: Results, quick: bool) -> dict:
    import yaml

    from digital_twin.prediction_engine import (
        FeatureSpec,
        build_features,
        link_tier,
        load_active,
        static_features,
    )
    from digital_twin.simulation_engine import run_scenario
    from netemu.network import EmulatedNetwork
    from netemu.topology import parse_topology

    from .twin import Twin

    raw = yaml.safe_load(CAMPUS.read_text(encoding="utf-8"))
    models = load_active(str(ROOT / "var" / "models"))
    model = models.get("short") or next(iter(models.values()))
    sizes = [(0, "campus"), (2, "about 40"), (17, "about 100"), (42, "about 200")]
    if quick:
        sizes = sizes[:2]
    out, rows = {}, []
    scratch = BACKEND / "evaluation" / "results" / "E7"
    scratch.mkdir(parents=True, exist_ok=True)
    for extra, label in sizes:
        topo = parse_topology(synthetic_topology(raw, extra))
        net = EmulatedNetwork(topo, datetime.fromisoformat("2026-11-03T10:00:00+01:00"), seed=11)
        net.random_faults = False
        twin = Twin(topo, net)
        twin.advance(3)
        ingest = []
        for _ in range(5 if quick else 20):
            twin.step_cycle()
            began = time.perf_counter()
            twin.ingest()
            ingest.append((time.perf_counter() - began) * 1000)
        core = twin.link_id("CORE-SW-01", "CORE-SW-02")
        simulate = []
        for _ in range(3 if quick else 5):
            began = time.perf_counter()
            run_scenario(twin.model, "link_failure", {"link_id": core})
            simulate.append((time.perf_counter() - began) * 1000)
        # forecasting: the trained forest works per link, so any number of links can be forecast
        n_links = len(topo.links)
        spec: FeatureSpec = model.spec
        history = int(spec.needed_history) + 5
        util = np.clip(np.random.default_rng(3).normal(40, 10, size=(history, n_links)), 0, 100).astype(np.float32)
        times = 1793000000 + 60.0 * np.arange(history)
        tiers = [link_tier((topo.devices[lk.a].role, topo.devices[lk.b].role),
                           (topo.devices[lk.a].type, topo.devices[lk.b].type)) for lk in topo.links]
        static = static_features(np.array([lk.capacity_mbps for lk in topo.links]), tiers)
        forecast = []
        for _ in range(3 if quick else 5):
            began = time.perf_counter()
            X = build_features(util, times, static, None, spec, np.array([history - 1]))[0]
            model.forest.predict(X)
            if model.classifier is not None:
                model.classifier.probability(X)
            forecast.append((time.perf_counter() - began) * 1000)
        elements = [{"group": "nodes", "data": {"id": name, "label": name},
                     "position": {"x": d.position[0] if d.position else 0, "y": d.position[1] if d.position else 0}}
                    for name, d in topo.devices.items()]
        elements += [{"group": "edges", "data": {"id": f"l{i}", "source": lk.a, "target": lk.b, "width": 2}}
                     for i, lk in enumerate(topo.links)]
        element_file = scratch / f"elements_{len(topo.devices)}.json"
        element_file.write_text(json.dumps(elements), encoding="utf-8")
        render = subprocess.run(["node", "scripts/e7_map_render.mjs", str(element_file), "3" if quick else "5"],
                                cwd=ROOT / "frontend", capture_output=True, text=True, timeout=600, check=False)
        element_file.unlink(missing_ok=True)
        map_ms = json.loads(render.stdout.strip().splitlines()[-1])["median_ms"] if render.returncode == 0 else None
        entry = {"devices": len(topo.devices), "links": n_links, "label": label,
                 "ingest_cycle_ms_median": round(statistics.median(ingest), 1),
                 "simulation_ms_median": round(statistics.median(simulate), 1),
                 "forecast_all_links_ms_median": round(statistics.median(forecast), 1),
                 "map_first_frame_ms_median": None if map_ms is None else round(map_ms, 1)}
        if map_ms is None:
            entry["map_error"] = render.stderr[-300:]
        out[str(len(topo.devices))] = entry
        rows.append(entry)
        twin.close()
        print(f"scale {entry['devices']} devices: {entry}")
    results.write_csv("scalability.csv", rows, ["devices", "links", "ingest_cycle_ms_median", "simulation_ms_median",
                                                "forecast_all_links_ms_median", "map_first_frame_ms_median"])
    figure, axes = chart(6.5, 3.2)
    devices = [r["devices"] for r in rows]
    for index, (key, label) in enumerate([("ingest_cycle_ms_median", "Ingest one cycle"),
                                          ("simulation_ms_median", "Run a link-failure simulation"),
                                          ("forecast_all_links_ms_median", "Forecast every link")]):
        axes.plot(devices, [r[key] for r in rows], marker="o", markersize=5, markeredgecolor="white",
                  color=SERIES[index], label=label)
    axes.set_xlabel("Devices in the network")
    axes.set_ylabel("Median time (ms)")
    axes.set_ylim(bottom=0)
    legend(axes, ncol=3)
    results.save_chart(figure, "scalability.png")
    return {"sizes": out}


def main() -> None:
    parser = argparse.ArgumentParser(description="E7 resources and scalability.")
    parser.add_argument("--parts", default="steady,database,api,scale")
    parser.add_argument("--url", default="https://localhost")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    results = Results("E7", "Resources and scalability (G4)",
                      config={"parts": parts, "quick": args.quick, "url": args.url})
    previous = results.folder / "results.json"
    if previous.exists():                      # keep parts measured in earlier runs
        results.summary = json.loads(previous.read_text(encoding="utf-8")).get("summary", {})
    if "steady" in parts:
        results.summary["steady"] = steady(results, 1 if args.quick else 10)
    if "database" in parts:
        results.summary["database"] = database()
    if "api" in parts:
        results.summary["api"] = api_load(results, args.url, [1, 3] if args.quick else [1, 3, 5], 20 if args.quick else 60)
    if "scale" in parts:
        results.summary["scale"] = scale(results, args.quick)
    services = (results.summary.get("steady") or {}).get("services", {})
    if services:
        results.summary["target"] = "runs within 4 GB of RAM"
        results.summary["target_met"] = (results.summary["steady"]["total_peak_mb"] < 4000)
    results.finish()
    print(json.dumps(results.summary, indent=2, default=str)[:3000])


if __name__ == "__main__":
    main()
