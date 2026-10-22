"""Topology import into the Topology Store, D1 (section 1.4: data "imported manually by the administrator").

Accepts the YAML/JSON topology format (devices + links). Validates everything
first, then writes in one transaction. Existing devices (by name) and links
(by device pair) are updated; nothing is deleted. Elements missing from the
file are left alone, and can be retired by setting status to "decommissioned".
A link to a device that has been retired is not imported; the report lists it.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.db import transaction

from .models import DeviceType, ElementStatus, NetworkDevice, NetworkLink

VALID_TYPES = {choice for choice, _ in DeviceType.choices}


@dataclass
class ImportReport:
    devices_created: int = 0
    devices_updated: int = 0
    links_created: int = 0
    links_updated: int = 0
    errors: list[str] = field(default_factory=list)
    links_skipped: list[str] = field(default_factory=list)   # links to a retired device (not an error)
    # Something the Digital Twin Engine loads when it starts was created or changed. Map
    # positions are not: the dashboard reads them straight from the store. False when the
    # file only moves devices on the map, or repeats what is stored.
    restart_needed: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors


def without_position(configuration: dict | None) -> dict:
    """A device's configuration less its map position: the part the network model uses."""
    return {key: value for key, value in (configuration or {}).items() if key != "position"}


def read_topology_file(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text) if str(path).lower().endswith(".json") else yaml.safe_load(text)


def validate(raw: dict) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    ips: set[str] = set()
    for i, d in enumerate(raw.get("devices") or []):
        where = f"device #{i + 1}"
        name = str(d.get("name", "")).strip()
        if not name:
            errors.append(f"{where}: name is required")
            continue
        if name in names:
            errors.append(f"{where}: duplicate name {name}")
        names.add(name)
        if d.get("type") not in VALID_TYPES:
            errors.append(f"{name}: type must be one of {sorted(VALID_TYPES)}")
        if d.get("ip"):
            try:
                ip = str(ipaddress.ip_address(str(d["ip"])))
            except ValueError:
                errors.append(f"{name}: invalid IP address {d['ip']}")
            else:
                if ip in ips:
                    errors.append(f"{name}: duplicate IP address {ip}")
                ips.add(ip)
    pairs: set[frozenset[str]] = set()
    for i, entry in enumerate(raw.get("links") or []):
        where = f"link #{i + 1}"
        if not isinstance(entry, list | tuple) or len(entry) < 3:
            errors.append(f"{where}: expected [device A, device B, capacity_mbps, optional cost]")
            continue
        a, b = str(entry[0]), str(entry[1])
        for n in (a, b):
            if n not in names:
                errors.append(f"{where}: unknown device {n}")
        if a == b:
            errors.append(f"{where}: a link cannot connect {a} to itself")
        try:
            capacity = float(entry[2])
            if capacity <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{where}: capacity must be a positive number of Mbps")
        if len(entry) > 3 and entry[3] is not None:
            try:
                if float(entry[3]) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{where}: routing cost must be a positive number")
        pair = frozenset((a, b))
        if pair in pairs:
            errors.append(f"{where}: duplicate link {a}-{b}")
        pairs.add(pair)
    if not names:
        errors.append("the file contains no devices")
    return errors


def import_topology(raw: dict, *, dry_run: bool = False) -> ImportReport:
    report = ImportReport(errors=validate(raw))
    if not report.ok:
        return report
    with transaction.atomic():
        by_name: dict[str, NetworkDevice] = {d.name: d for d in NetworkDevice.objects.all()}
        for d in raw["devices"]:
            config = {
                "role": d.get("role", ""),
                "zone": d.get("zone", ""),
                "position": list(d.get("position", [0, 0])),
                "internet_egress": bool(d.get("internet_egress", False)),
            }
            fields = {"device_type": d["type"], "ip_address": str(d["ip"]) if d.get("ip") else None,
                      "location": d.get("location", "")}
            device = by_name.get(d["name"])
            if device is None:
                device = NetworkDevice.objects.create(name=d["name"], configuration=config, **fields)
                by_name[device.name] = device
                report.devices_created += 1
                report.restart_needed = True
            else:
                before = ({key: getattr(device, key) for key in fields}, without_position(device.configuration))
                for key, value in fields.items():
                    setattr(device, key, value)
                device.configuration = {**(device.configuration or {}), **config}
                device.save()
                report.devices_updated += 1
                if before != (fields, without_position(device.configuration)):
                    report.restart_needed = True
        existing = {frozenset((lk.source_device_id, lk.dest_device_id)): lk
                    for lk in NetworkLink.objects.all()}
        for entry in raw.get("links") or []:
            a, b = by_name[str(entry[0])], by_name[str(entry[1])]
            retired = [d.name for d in (a, b) if d.status == ElementStatus.DECOMMISSIONED]
            if retired:   # a link to a retired device cannot be in service, and the import sets no status
                which = f"{retired[0]} is" if len(retired) == 1 else f"{retired[0]} and {retired[1]} are"
                report.links_skipped.append(f"{a.name} <-> {b.name}: not imported, because {which} decommissioned")
                continue
            capacity = float(entry[2])
            cost = float(entry[3]) if len(entry) > 3 and entry[3] is not None else None
            link = existing.get(frozenset((a.device_id, b.device_id)))
            if link is None:
                NetworkLink.objects.create(source_device=a, dest_device=b, capacity_mbps=capacity,
                                           routing_cost=cost)
                report.links_created += 1
                report.restart_needed = True
            else:
                if (link.capacity_mbps, link.routing_cost) != (capacity, cost):
                    report.restart_needed = True
                link.capacity_mbps = capacity
                link.routing_cost = cost
                link.save(update_fields=["capacity_mbps", "routing_cost"])
                report.links_updated += 1
        if dry_run:
            transaction.set_rollback(True)
    return report
