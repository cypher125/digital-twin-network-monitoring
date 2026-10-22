"""Adapter for an HTTP telemetry feed (Figure 3.2: "SNMP polling / telemetry feed").

Reads the network emulator's read-only feed: SNMP-style counters, NetFlow-style
flow records and trap-style events. It only issues GET requests. If the source
restarts and numbers its records from the start again, the adapter notices (the
source's latest number is behind its cursor) and carries on from the new records.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from .base import DeviceSample, FlowSample, InterfaceSample, RawBatch, RawEvent


class TelemetryHttpAdapter:
    name = "telemetry_http"

    def __init__(self, base_url: str, timeout: float = 10.0, flows_from_now: bool = True):
        # One keep-alive client; always use 127.0.0.1 rather than localhost (plan section 12.1).
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self.event_client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout + 35)
        self._flow_cursor: int | None = None
        self._event_cursor: int | None = None
        self._flows_from_now = flows_from_now

    def close(self) -> None:
        self.client.close()
        self.event_client.close()

    def describe(self) -> dict:
        response = self.client.get("/v1/info")
        response.raise_for_status()
        return response.json()

    def poll(self) -> RawBatch:
        response = self.client.get("/v1/snapshot")
        response.raise_for_status()
        received_at = datetime.now(UTC)
        snapshot = response.json()
        devices = [self._device(d) for d in snapshot["devices"]]
        flows, flow_seconds = self._flows()
        return RawBatch(
            source=self.name,
            measured_at=datetime.fromisoformat(snapshot["timestamp"]),
            received_at=received_at,
            devices=devices,
            flows=flows,
            flow_seconds=flow_seconds,
        )

    def events(self, wait_seconds: float) -> list[RawEvent]:
        if self._event_cursor is None:
            first = self.event_client.get("/v1/events", params={"after": 0})
            first.raise_for_status()
            self._event_cursor = first.json()["latest"]  # only events from now on
        response = self.event_client.get(
            "/v1/events", params={"after": self._event_cursor, "wait": wait_seconds})
        response.raise_for_status()
        received_at = datetime.now(UTC)
        body = response.json()
        if body.get("latest", self._event_cursor) < self._event_cursor:
            # the source restarted and numbers its events from 1 again: read them from the start
            self._event_cursor = 0
            response = self.event_client.get("/v1/events", params={"after": 0})
            response.raise_for_status()
            body = response.json()
        events = [
            RawEvent(seq=e["seq"], time=datetime.fromisoformat(e["time"]), type=e["type"],
                     element=e["element"], detail=e.get("detail", ""), received_at=received_at)
            for e in body["events"]
        ]
        if events:
            self._event_cursor = max(e.seq for e in events)
        return events

    # ------------------------------------------------------------------
    @staticmethod
    def _device(d: dict) -> DeviceSample:
        if not d.get("reachable", False):
            return DeviceSample(device=d["name"], reachable=False)
        interfaces = tuple(
            InterfaceSample(
                device=d["name"],
                if_index=int(i["ifIndex"]),
                peer=i["peer"],
                in_octets=int(i["ifHCInOctets"]),
                out_octets=int(i["ifHCOutOctets"]),
                in_errors=int(i["ifInErrors"]),
                oper_up=int(i["ifOperStatus"]) == 1,
                speed_mbps=float(i["ifSpeedMbps"]),
            )
            for i in d.get("interfaces", [])
        )
        return DeviceSample(device=d["name"], reachable=True, uptime_ticks=int(d["sysUpTime"]),
                            cpu_pct=float(d["cpu"]), interfaces=interfaces)

    def _flows(self) -> tuple[list[FlowSample], float]:
        if self._flow_cursor is None and self._flows_from_now:
            first = self.client.get("/v1/flows", params={"after": 10 ** 12})
            first.raise_for_status()
            self._flow_cursor = first.json()["latest"]
            return [], 0.0
        response = self.client.get("/v1/flows", params={"after": self._flow_cursor or 0})
        response.raise_for_status()
        body = response.json()
        if self._flow_cursor and body.get("latest", self._flow_cursor) < self._flow_cursor:
            # the source restarted and numbers its cycles again: read its new cycles
            self._flow_cursor = 0
            response = self.client.get("/v1/flows", params={"after": 0})
            response.raise_for_status()
            body = response.json()
        cycles = body["cycles"]
        if not cycles:
            return [], 0.0
        self._flow_cursor = max(c["seq"] for c in cycles)
        start = min(datetime.fromisoformat(c["start"]) for c in cycles)
        end = max(datetime.fromisoformat(c["end"]) for c in cycles)
        totals: dict[tuple[str, str, str], list[int]] = {}
        for cycle in cycles:
            for r in cycle["records"]:
                key = (r["src"], r["dst"], r["cls"])
                acc = totals.setdefault(key, [0, 0])
                acc[0] += int(r["octets_fwd"])
                acc[1] += int(r["octets_rev"])
        flows = [FlowSample(src, dst, cls, fwd, rev) for (src, dst, cls), (fwd, rev) in totals.items()]
        return flows, (end - start).total_seconds()
