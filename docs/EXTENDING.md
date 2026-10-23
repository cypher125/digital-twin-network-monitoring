# Extending the system (NFR5 modularity)

NFR5 asks for a modular design that can be extended without reworking the rest of the system. This document shows the two extension points of §3.3, worked through on real code:

1. **adding a scenario type**, so administrators can try a new kind of change;
2. **adding a network adapter**, so the twin can read a new kind of data source.

Both were carried out on a copy of the repository (a git worktree at commit `9266780`), tested, and then removed so that the delivered system still matches Chapter 3. The complete change is in [`docs/evidence/NFR5_extension_example.diff`](evidence/NFR5_extension_example.diff).

## What it took

| | Files touched | Lines added | Lines changed | Engine, API or dashboard changed? |
|---|---|---|---|---|
| New scenario type "Link degradation" | 3 code + 1 generated migration + 1 test | 49 | 1 | No |
| New adapter "snapshot-replay" | 1 new module + 1 registry line + 1 test | 74 | 0 | No |
| **Total** | **7** | **123** | **1** | **No** |

- Afterwards, 37 unit tests in the three affected test files passed.
- Ruff found no issues, and all five import-linter layering contracts were kept.

These rules keep each change this small:
- **The simulation engine and the dashboard never list the scenario types themselves.** The API sends the registry's description of every type (`GET /api/v1/scenario-types`). The dashboard builds the type cards and the guided forms from that description.
- **The engine only knows the `NetworkAdapter` interface** (`describe`, `poll`, `events`, `close`). It is handed an adapter object when it starts; only the command that starts it (`run_twin`) chooses which one, from the adapter registry.

## 1. Adding a scenario type

The example is **Link degradation**: "What if a link ran slower than its rated speed, for example after a duplex mismatch?" The administrator picks a link and the share of its speed that is left.

**Step 1: describe, validate and apply the change** (`backend/digital_twin/simulation_engine/scenarios.py`, 19 lines).

Two functions:
- `_v_degradation` checks the parameters and returns clear messages.
- `_a_degradation` changes the **detached copy** of the model it is given. It never sees the live model, so a new type cannot break G3.

```python
def _v_degradation(params, model):
    return {"link_id": _link(params, model),
            "percent": _number(params, "percent", minimum=1, maximum=99, label="speed left (%)")}


def _a_degradation(model, demands, params):
    edge = model.link(params["link_id"])
    old = edge["capacity_mbps"]
    edge["capacity_mbps"] = old * params["percent"] / 100
    return Change(list(demands), notes=[
        f"{model.link_label(params['link_id'])} runs at {params['percent']:g}% of its {old:g} Mbps."])
```

**Step 2: register it**, with its label, a description and the form fields, in the same file:

```python
    ScenarioType("link_degradation", "Link degradation",
                 "What if a link ran slower than its rated speed, for example after a duplex mismatch?",
                 [{"name": "link_id", "label": "Link", "type": "link", "required": True},
                  {"name": "percent", "label": "Speed left (%)", "type": "number", "min": 1, "max": 99,
                   "required": True}],
                 _v_degradation, _a_degradation),
```

The field types (`link`, `device`, `number`, `class`, `zone`, `destination`, `links`, `link_costs`) are the ones the dashboard's guided form already knows. A new type that uses them needs no frontend change.

**Step 3: allow the new value in the database** (`backend/apps/twin/models.py`, one line). Then let Django write the migration:

```python
    LINK_DEGRADATION = "link_degradation", "Link degradation"
```
```powershell
.venv\Scripts\python.exe manage.py makemigrations twin -n link_degradation_type
```

The migration only changes the list of allowed values. No table changes.

**Step 4: test it** (`backend/tests/unit/test_simulation.py`).
- Add the key to `test_registry_covers_every_scenario_type`.
- Add one behaviour test: halving the 100 Mbps access link that carries 50 Mbps makes it 100 % full and a new bottleneck, and 100 % is refused with a clear message.

**What happens without further changes:**
- The **simulation console** shows the new card and its form.
- The **API** validates and stores scenarios of the new type, runs them and returns before/after results.
- The **result page** shows the table, the bottlenecks created or relieved, the summary and the after-change map.
- The **recommendation engine** is not affected. It only uses the types it was written for (routing change, reroute traffic, QoS policy and capacity change). A new type becomes a recommendation only if it is added to `recommendations.py` on purpose.

## 2. Adding a network adapter

The example is **snapshot-replay**: it reads a file of feed snapshots recorded earlier, one per monitoring cycle, so a recorded incident can be run through the twin again. An SNMP adapter for real devices would follow the same steps, with `poll()` reading the IF-MIB counters (`ifHCInOctets`, `ifHCOutOctets`, `ifInErrors`, `ifOperStatus`, `ifSpeed`) with read-only credentials.

**Step 1: implement the interface** in a new module, `backend/data_collection/network_adapter/snapshot_replay.py` (49 lines). An adapter turns its source's data into the twin's neutral raw types (`RawBatch`, `DeviceSample`, `InterfaceSample`, `FlowSample`, `RawEvent`). Preprocessing, the network model, storage and prediction then work exactly as with the emulator feed.

```python
class SnapshotReplayAdapter:
    name = "snapshot-replay"

    def __init__(self, source: str): ...            # read the recording
    def describe(self) -> dict: ...                  # name, mode, clock, cycle length
    def poll(self) -> RawBatch: ...                  # the next recorded cycle
    def events(self, wait_seconds: float) -> list[RawEvent]: ...   # none in a recording
    def close(self) -> None: ...
```

Adapters only read. The unit test `test_every_registered_adapter_is_read_only_and_complete` checks every adapter in the registry. It fails if an adapter has any public method other than these four, or lacks one of them (G3 and §3.8).

**Step 2: register it** (`backend/data_collection/network_adapter/__init__.py`, two lines: the import and the registry entry):

```python
ADAPTERS: dict[str, Callable[[str], NetworkAdapter]] = {
    "telemetry-http": TelemetryHttpAdapter,
    "snapshot-replay": SnapshotReplayAdapter,
}
```

**Step 3: run the twin with it.** Nothing else changes:

```powershell
.venv\Scripts\python.exe manage.py run_twin --adapter snapshot-replay --source recorded.jsonl
```

**Step 4: test it** (`backend/tests/unit/test_adapter.py`). The new test records three cycles from the emulator and replays them through the registry and the real preprocessor. It checks that every link of the campus network comes out with a clean reading.

## Where the boundaries are enforced

| Rule | Enforced by |
|---|---|
| The engine core does not depend on Django or the web layer | import-linter contract "engine core is independent of the web framework" |
| The simulation engine cannot reach any adapter, so it has no path to the network | import-linter contract (G3) |
| No part of the twin uses the emulator's lab interface | import-linter contract and `test_no_part_of_the_twin_uses_the_lab_interface` |
| Every adapter is read-only and complete | `test_every_registered_adapter_is_read_only_and_complete` |
| Every scenario type has a description and a form | `test_registry_covers_every_scenario_type` |
| Scenario changes only touch a detached copy | `test_live_model_is_never_modified` |

The contracts are in `backend/pyproject.toml` under `[tool.importlinter]`. Run them with `.venv\Scripts\lint-imports.exe`.
