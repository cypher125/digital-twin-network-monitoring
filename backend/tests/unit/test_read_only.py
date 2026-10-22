"""The system has no write path to the network (section 3.8, gap G3).

Three layers of protection are checked here, alongside the import-linter contracts:
1. the adapter interface offers read operations only;
2. adapters never send write requests or SNMP SET commands;
3. no part of the twin (collection, engine, web apps) talks to the emulator's lab interface,
   which is the only way to change the emulated "real network".
"""
import inspect
from pathlib import Path

import data_collection
import digital_twin
from data_collection.network_adapter import NetworkAdapter, TelemetryHttpAdapter

BACKEND = Path(__file__).resolve().parents[2]
ALLOWED = {"describe", "poll", "events", "close"}
TWIN_PACKAGES = [Path(data_collection.__file__).parent, Path(digital_twin.__file__).parent,
                 BACKEND / "apps" / "twin", BACKEND / "apps" / "api", BACKEND / "apps" / "accounts"]


def sources(folders):
    for folder in folders:
        for path in folder.rglob("*.py"):
            yield path, path.read_text(encoding="utf-8")


def test_adapter_interface_has_only_read_operations():
    public = {name for name, _ in inspect.getmembers(NetworkAdapter, inspect.isfunction) if not name.startswith("_")}
    assert public <= ALLOWED


def test_telemetry_adapter_exposes_only_read_operations():
    public = {name for name, _ in inspect.getmembers(TelemetryHttpAdapter, inspect.isfunction)
              if not name.startswith("_")}
    assert public <= ALLOWED


HTTP_WRITES = [f"{client}.{verb}(" for client in ("httpx", "client", "self.client", "event_client", "requests")
               for verb in ("post", "put", "patch", "delete")]
SNMP_WRITES = ["SetCommand", "setCmd", "set_cmd"]


def test_collection_and_engine_never_send_write_requests():
    """No HTTP write requests and no SNMP SET anywhere in collection or the engine.

    (Database deletes for data retention are not network writes and are allowed.)"""
    for path, source in sources(TWIN_PACKAGES[:2]):
        for verb in HTTP_WRITES + SNMP_WRITES:
            assert verb not in source, f"{path.relative_to(BACKEND)} contains {verb}"


def test_no_part_of_the_twin_uses_the_lab_interface():
    for path, source in sources(TWIN_PACKAGES):
        for marker in ("/lab/", "X-Lab-Token", "LabClient", "lab_client", "NETEMU_LAB_TOKEN"):
            assert marker not in source, f"{path.relative_to(BACKEND)} mentions {marker}"
