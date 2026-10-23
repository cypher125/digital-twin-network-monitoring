"""E8 Functional acceptance: every requirement and use-case step, with its evidence and pass/fail.

The matrix is the traceability matrix of the project plan (§14) made executable. Each row lists
the evidence that verifies it:

- automated tests, read from a pytest JUnit report (the whole suite, slow tests included);
- steps of the Playwright walkthrough of UC1-UC4 (frontend/scripts/walkthrough.mjs), read from
  its report.json, by default from the latest run (var/walkthrough/report.json);
- experiments E1-E9, read from evaluation/results/<E>/results.json;
- the import-linter layering contracts (NFR5), run here;
- documents and evidence files that must exist.

A row passes when all its evidence passes; it is "pending" while an experiment it relies on
has not been run yet. The success criterion of E8 is that every FR and use-case row passes.

    python -m evaluation.e8_functional_matrix               (runs the test suite, about 10 min)
    python -m evaluation.e8_functional_matrix --reuse-tests (uses the last JUnit report)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .common import BACKEND, RESULTS, ROOT, Results


@dataclass
class Evidence:
    kind: str     # test | walkthrough | experiment | lint | file
    ref: str
    status: str = "missing"   # pass | fail | pending | missing
    detail: str = ""


@dataclass
class Row:
    req: str
    source: str
    text: str
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def status(self) -> str:
        states = {e.status for e in self.evidence}
        if "fail" in states or "missing" in states:
            return "fail"
        if "pending" in states:
            return "pending"
        return "pass"


def T(nodeid: str) -> Evidence:
    return Evidence("test", nodeid)


def W(step: str) -> Evidence:
    return Evidence("walkthrough", step)


def E(experiment: str) -> Evidence:
    return Evidence("experiment", experiment)


def F(path: str) -> Evidence:
    return Evidence("file", path)


LINT = Evidence("lint", "lint-imports (import-linter contracts in pyproject.toml)")

UT, IT = "tests/unit/", "tests/integration/"
SIGN_IN = "Senior Administrator signs in"

MATRIX = [
    # ---------------------------------------------------------------- functional requirements
    Row("FR1", "§3.4.1, O1", "Represent the topology as a dynamic graph with node and edge attributes and configuration", [
        T(UT + "test_network_model.py::test_graph_mirrors_topology"),
        T(IT + "test_database.py::test_topology_import_creates_devices_links_and_configuration"),
        T(IT + "test_database.py::test_topology_import_is_idempotent"),
        T(IT + "test_database.py::test_topology_import_refuses_bad_files"),
        T(IT + "test_api.py::test_topology_payload"),
        E("E1")]),
    Row("FR2", "§3.4.1, O2", "Synchronise the model with monitoring data periodically and on events", [
        T(UT + "test_pipeline_smoke.py::test_twin_replicates_emulator_state"),
        T(UT + "test_pipeline_smoke.py::test_events_arrive_through_the_feed"),
        T(UT + "test_preprocessing.py::test_counter_delta_handles_wrap_and_reset"),
        T(UT + "test_preprocessing.py::test_spike_is_rejected_and_baseline_kept"),
        T(UT + "test_preprocessing.py::test_unreachable_device_marks_link_down"),
        T(UT + "test_network_model.py::test_apply_updates_state_and_reports_status_changes"),
        T(IT + "test_engine.py::test_each_cycle_is_stored_once_and_published"),
        T(IT + "test_engine.py::test_a_late_poll_counts_and_reports_the_cycles_it_missed"),
        T(UT + "test_adapter.py::test_flow_and_event_cursors_survive_a_source_restart"),
        E("E1")]),
    Row("FR3", "§3.4.1, O3", "Analyse trends, forecast utilisation and warn before congestion, with lead time", [
        T(UT + "test_prediction.py::test_forest_beats_naive_baselines_at_thirty_minutes"),
        T(UT + "test_prediction.py::test_rising_link_is_flagged_at_least_ten_minutes_early"),
        T(UT + "test_prediction.py::test_features_never_look_ahead"),
        T(UT + "test_prediction.py::test_online_and_offline_features_agree"),
        T(UT + "test_prediction.py::test_alert_episode_lifecycle_with_hysteresis"),
        T(IT + "test_api.py::test_link_metrics_and_forecast"),
        E("E2"), E("E3")]),
    Row("FR4", "§3.4.1, O4", "Test changes on a detached copy and show bottlenecks created or relieved", [
        T(UT + "test_simulation.py::test_live_model_is_never_modified"),
        T(UT + "test_simulation.py::test_registry_covers_every_scenario_type"),
        T(UT + "test_simulation.py::test_link_failure_reroutes_over_the_other_core"),
        T(UT + "test_simulation.py::test_traffic_increase_creates_a_bottleneck"),
        T(UT + "test_simulation.py::test_capacity_upgrade_relieves_load"),
        T(UT + "test_simulation.py::test_invalid_parameters_give_clear_messages"),
        T(UT + "test_sim_vs_reality.py::test_prediction_matches_reality"),
        T(IT + "test_api.py::test_scenario_lifecycle"),
        E("E4")]),
    Row("FR5", "§3.4.1, O5", "Web dashboard with a live topology view", [
        W("UC1 overview shows the live map and summary"),
        W("System page shows the engine, models and database"),
        T(IT + "test_api.py::test_live_reports_state_version"),
        T(IT + "test_api.py::test_an_edit_shows_at_once_not_at_the_next_cycle"),
        E("E5")]),
    # ---------------------------------------------------------------- use cases (Figure 3.5)
    Row("UC1", "Figure 3.5", "Monitor network topology in real time", [
        W(SIGN_IN), W("UC1 overview shows the live map and summary"),
        W("NFR1: the overview shows each new cycle within 5 s of it being stored")]),
    Row("UC1-ext", "Figure 3.5", "View device / link detail", [
        W("UC1 extension: open a link's detail from the links table"),
        W("UC1 extension: open a device's detail")]),
    Row("UC2", "Figure 3.5", "Receive predictive congestion alerts (link, time, confidence, recommendation)", [
        W("UC2: a surge in the network raises a predictive alert"),
        T(IT + "test_engine.py::test_fixes_for_a_new_alert_are_worked_out_off_the_cycle"),
        T(IT + "test_api.py::test_active_alerts_say_when_the_model_was_trained"),
        E("E3")]),
    Row("UC2-ext", "Figure 3.5", "View trend and forecast chart", [
        W("UC2 alerts page shows alerts (or that none are expected) and the history"),
        T(IT + "test_api.py::test_link_metrics_and_forecast")]),
    Row("UC3", "Figure 3.5", "Run a what-if simulation", [
        W("UC3: create and run a link-failure scenario with the guided form"),
        T(IT + "test_api.py::test_scenario_lifecycle"),
        T(IT + "test_database.py::test_queued_simulation_is_run_and_stored"),
        E("E4")]),
    Row("UC3-ext", "Figure 3.5", "Compare scenario result with current state", [
        W("UC3 extension: compare the result with the network now"),
        T(IT + "test_api.py::test_result_compare")]),
    Row("UC4", "Weakness 3 (§3.7)", "Analyse long-term trends and plan capacity", [
        W("UC4: trends, weekly pattern and capacity planning"),
        T(IT + "test_api.py::test_trends_capacity_and_export"),
        T(IT + "test_api.py::test_network_trend_covers_up_to_14_days"),
        T(IT + "test_api.py::test_capacity_planning_fits_complete_days_only"),
        E("E9")]),
    Row("Auth", "Figure 3.5 «include»", "Authenticate (log in) with two roles", [
        W("Sign-in refuses a wrong password"), W(SIGN_IN), W("Senior Administrator signs out"),
        W("Junior Administrator can look but not change anything"),
        T(IT + "test_api.py::test_every_endpoint_needs_a_login"),
        T(IT + "test_api.py::test_junior_can_read_everything_but_change_nothing"),
        T(IT + "test_api.py::test_user_without_a_role_cannot_log_in")]),
    # ---------------------------------------------------------------- non-functional requirements
    Row("NFR1", "§3.4.2", "Responsiveness: new data on screen within 5 s", [
        W("NFR1: the overview shows each new cycle within 5 s of it being stored"),
        T(IT + "test_engine.py::test_the_published_network_time_is_never_behind_the_stored_cycle"),
        T(IT + "test_api.py::test_polls_do_not_count_as_activity"),
        E("E5")]),
    Row("NFR2", "§3.4.2", "Reliability: runs unattended and recovers from faults", [
        T(UT + "test_netemu.py::test_a_locked_clock_file_never_stops_the_network"),
        T(UT + "test_adapter.py::test_flow_and_event_cursors_survive_a_source_restart"),
        T(IT + "test_database.py::test_duplicate_readings_are_impossible"),
        T(IT + "test_database.py::test_model_starts_warm_from_the_latest_readings"),
        F("docs/evidence/P6_recovery.json"),
        E("E6")]),
    Row("NFR3", "§3.4.2", "Usability for administrators without data-science training", [
        F("docs/evaluation/E8_USABILITY_KIT.md"),
        Evidence("experiment", "E8-SUS")]),
    Row("NFR4", "§3.4.2, §3.8", "Security: authentication, roles, HTTPS, CSRF, throttling, audit", [
        T(IT + "test_api.py::test_login_is_csrf_protected"),
        T(IT + "test_api.py::test_password_checks_are_rate_limited"),
        T(IT + "test_api.py::test_repeated_failures_lock_the_account"),
        T(IT + "test_api.py::test_senior_needs_recent_activity_to_make_changes"),
        T(IT + "test_api.py::test_reading_after_an_absence_does_not_unlock_changes"),
        T(IT + "test_api.py::test_junior_is_never_write_allowed"),
        T(IT + "test_api.py::test_sign_ins_changes_and_runs_are_audited"),
        T(IT + "test_admin.py::test_a_senior_manages_accounts_but_cannot_grant_superuser_or_extra_groups"),
        T(UT + "test_settings_prod.py::test_production_settings_are_locked_down"),
        T(UT + "test_settings_prod.py::test_production_refuses_to_start_without_a_secret_key"),
        T(UT + "test_pipeline_smoke.py::test_lab_needs_the_token"),
        F("docs/evidence/P6_security_headers.txt")]),
    Row("NFR5", "§3.4.2", "Modularity: layered packages, pluggable adapters and scenario types", [
        LINT,
        T(UT + "test_simulation.py::test_registry_covers_every_scenario_type"),
        T(UT + "test_read_only.py::test_adapter_interface_has_only_read_operations"),
        F("docs/EXTENDING.md")]),
    # ---------------------------------------------------------------- goals and other design points
    Row("G1", "§3.2", "A live replica of the network", [E("E1")]),
    Row("G2", "§3.2", "Forecasts bound to links, with alerts", [E("E3")]),
    Row("G3", "§3.2, §3.8", "Changes tested on a detached copy with no write path to the network", [
        T(UT + "test_read_only.py::test_collection_and_engine_never_send_write_requests"),
        T(UT + "test_read_only.py::test_no_part_of_the_twin_uses_the_lab_interface"),
        T(UT + "test_read_only.py::test_telemetry_adapter_exposes_only_read_operations"),
        T(UT + "test_simulation.py::test_live_model_is_never_modified"),
        LINT, E("E4")]),
    Row("G4", "§3.2", "Affordable, open source, administrator-first", [
        F("docs/INSTALL.md"), F("docs/USER_GUIDE.md"), E("E7"), Evidence("experiment", "E8-SUS")]),
    Row("Optimisation", "§3.2 (title)", "Recommend tested fixes for predicted congestion", [
        T(UT + "test_simulation.py::test_recommendations_prefer_least_disruptive_fix"),
        T(UT + "test_simulation.py::test_recommendations_for_a_link_with_no_alternative_path"),
        T(IT + "test_engine.py::test_fixes_for_a_new_alert_are_worked_out_off_the_cycle"),
        E("E4")]),
    Row("Tables 3.2/3.3", "§3.6", "The six tables, their principal fields and relationships", [
        T(IT + "test_schema.py::test_the_six_tables_exist_with_every_principal_field"),
        T(IT + "test_schema.py::test_primary_keys_are_the_named_id_fields"),
        T(IT + "test_schema.py::test_table_3_3_relationships_are_foreign_keys_in_the_database"),
        T(IT + "test_schema.py::test_history_is_protected_from_cascading_deletes"),
        T(IT + "test_database.py::test_monitoring_record_is_device_or_link_never_both"),
        T(IT + "test_database.py::test_utilisation_must_be_a_percentage"),
        T(UT + "test_simulation.py::test_result_fits_the_simulation_result_table")]),
    Row("Figure 3.4", "§3.5", "Data flow: processes 1.0-6.0 and stores D1-D4", [
        T(UT + "test_pipeline_smoke.py::test_twin_replicates_emulator_state"),
        T(IT + "test_database.py::test_write_cycle_stores_one_row_per_link_and_device"),
        F("docs/diagrams/dfd.svg")]),
]

FUNCTIONAL = {"FR1", "FR2", "FR3", "FR4", "FR5", "UC1", "UC1-ext", "UC2", "UC2-ext", "UC3", "UC3-ext", "UC4", "Auth"}


# ------------------------------------------------------------------------ evidence readers
def run_tests(junit) -> int:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1"}
    if "DATABASE_URL" not in env and not (BACKEND / ".env").exists():
        print("warning: no DATABASE_URL and no backend/.env, so the integration tests cannot reach PostgreSQL")
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
    print("running the test suite (slow tests included):", " ".join(command[2:]))
    return subprocess.run(command, cwd=BACKEND, env=env).returncode


def read_junit(path) -> dict[str, tuple[str, str]]:
    """nodeid -> (pass | fail, message)."""
    out = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        module = case.get("classname", "").replace(".", "/")
        nodeid = f"{module}.py::{case.get('name')}"
        failure = case.find("failure")
        if failure is None:     # (an Element without children is falsy, so no `or` here)
            failure = case.find("error")
        if failure is not None:
            out[nodeid] = ("fail", (failure.get("message") or "")[:200])
        elif case.find("skipped") is not None:
            out[nodeid] = ("missing", "skipped")
        else:
            out[nodeid] = ("pass", f"{float(case.get('time', 0)):.2f} s")
    return out


def experiment_status(name: str) -> tuple[str, str]:
    if name == "E8-SUS":
        path = RESULTS / "E8_usability" / "results.json"
        if not path.exists():
            return "pending", "usability sessions not run yet"
        summary = json.loads(path.read_text(encoding="utf-8")).get("summary", {})
        staff = summary.get("staff", {})
        if not summary.get("enough_participants"):
            return "pending", f"{staff.get('participants', 0)} staff participants so far (5 needed)"
        return "pass", f"SUS {staff.get('sus_mean')} ({staff.get('band')}), n = {staff.get('participants')}"
    path = RESULTS / name / "results.json"
    if not path.exists():
        return "pending", "not run yet"
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    if data.get("config", {}).get("quick") or summary.get("quick"):
        return "pending", "only a quick run so far"
    verdict = summary.get("verdict")
    targets = {k: v for k, v in summary.items() if k.startswith("target") and isinstance(v, dict) and "met" in v}
    if isinstance(verdict, dict):
        passed, criterion = verdict.get("passed"), verdict.get("criterion", "")
    elif targets:   # {"target_x": {"rule": ..., "met": bool}, ...}
        passed = all(bool(v["met"]) for v in targets.values())
        criterion = "; ".join(f"{v.get('rule', k)}: {'met' if v['met'] else 'not met'}" for k, v in targets.items())
    else:
        passed, criterion = verdict if isinstance(verdict, bool) else summary.get("passed"), ""
    if passed is None:
        return "pass", "ran; see its results (no pass/fail criterion recorded)"
    return ("pass" if passed else "fail"), criterion


def lint_status() -> tuple[str, str]:
    tool = BACKEND / ".venv" / "Scripts" / "lint-imports.exe"
    command = [str(tool)] if tool.exists() else [sys.executable, "-m", "importlinter.cli"]
    done = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace")
    kept = [line.strip() for line in done.stdout.splitlines() if "KEPT" in line or "BROKEN" in line]
    return ("pass" if done.returncode == 0 else "fail"), "; ".join(kept)[:400]


def main() -> None:
    parser = argparse.ArgumentParser(description="E8 functional acceptance matrix.")
    parser.add_argument("--reuse-tests", action="store_true", help="use the last JUnit report instead of rerunning")
    parser.add_argument("--walkthrough", default=None, help="walkthrough report.json (default: the latest run)")
    args = parser.parse_args()

    results = Results("E8", "Functional acceptance matrix", config={"source": "project plan §14 and §9"})
    junit = results.folder / "junit.xml"
    if not (args.reuse_tests and junit.exists()):
        run_tests(junit)
    tests = read_junit(junit)

    walk_path = args.walkthrough or next(
        (p for p in (ROOT / "var" / "walkthrough" / "report.json", ROOT / "docs" / "evidence" / "P5_walkthrough_report.json")
         if p.exists()), None)
    walk = json.loads(open(walk_path, encoding="utf-8").read()) if walk_path else {"steps": []}
    steps = {s["name"]: s for s in walk.get("steps", [])}
    lint = lint_status()

    for row in MATRIX:
        for ev in row.evidence:
            if ev.kind == "test":
                ev.status, ev.detail = tests.get(ev.ref, ("missing", "test not found in the report"))
            elif ev.kind == "walkthrough":
                step = steps.get(ev.ref)
                ev.status = "missing" if step is None else ("pass" if step["ok"] else "fail")
                ev.detail = "" if step is None else (step.get("detail") or f"{step.get('seconds')} s")
            elif ev.kind == "experiment":
                ev.status, ev.detail = experiment_status(ev.ref)
            elif ev.kind == "lint":
                ev.status, ev.detail = lint
            elif ev.kind == "file":
                ev.status = "pass" if (ROOT / ev.ref).exists() else "missing"

    flat = [{"requirement": row.req, "source": row.source, "requirement_text": row.text, "row_status": row.status,
             "evidence_kind": ev.kind, "evidence": ev.ref, "evidence_status": ev.status, "detail": ev.detail}
            for row in MATRIX for ev in row.evidence]
    results.write_csv("functional_matrix.csv", flat)

    lines = ["| Requirement | Source | What is verified | Evidence | Result |", "|---|---|---|---|---|"]
    for row in MATRIX:
        counts = {}
        for ev in row.evidence:
            counts.setdefault(ev.kind, []).append(ev)
        parts = []
        for kind, evs in counts.items():
            ok = sum(e.status == "pass" for e in evs)
            label = {"test": "tests", "walkthrough": "walkthrough steps", "experiment": "experiments",
                     "lint": "import-linter", "file": "documents"}[kind]
            names = ", ".join(e.ref for e in evs) if kind in ("experiment", "file") else ""
            parts.append(f"{label} {ok}/{len(evs)}" + (f" ({names})" if names else ""))
        lines.append(f"| {row.req} | {row.source} | {row.text} | {'; '.join(parts)} | **{row.status}** |")
    (results.folder / "functional_matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    functional = [r for r in MATRIX if r.req in FUNCTIONAL]
    automated = [ev for row in MATRIX for ev in row.evidence if ev.kind in ("test", "walkthrough", "lint")]
    results.summary = {
        "rows": len(MATRIX),
        "rows_pass": sum(r.status == "pass" for r in MATRIX),
        "rows_pending": [r.req for r in MATRIX if r.status == "pending"],
        "rows_fail": [r.req for r in MATRIX if r.status == "fail"],
        "functional_rows_pass": f"{sum(r.status == 'pass' for r in functional)}/{len(functional)}",
        "automated_evidence_pass": f"{sum(e.status == 'pass' for e in automated)}/{len(automated)}",
        "tests_in_suite": len(tests),
        "tests_passed": sum(v[0] == "pass" for v in tests.values()),
        "walkthrough": {"file": str(walk_path), "url": walk.get("url"), "when": walk.get("when"),
                        "passed": walk.get("passed"), "failed": walk.get("failed")},
        "failures": [f"{row.req}: {ev.kind} {ev.ref} ({ev.status}) {ev.detail}" for row in MATRIX
                     for ev in row.evidence if ev.status in ("fail", "missing")],
        "verdict": {"passed": all(r.status != "fail" for r in functional) and all(
            ev.status == "pass" for r in functional for ev in r.evidence if ev.kind != "experiment"),
                    "criterion": "every FR and use-case row passes its tests and walkthrough steps"},
    }
    results.finish()
    print(json.dumps(results.summary, indent=1))


if __name__ == "__main__":
    main()
