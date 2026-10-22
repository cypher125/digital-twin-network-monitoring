"""The telemetry adapter keeps working when the source restarts and numbers its records again."""
import httpx

from data_collection.network_adapter.telemetry_http import TelemetryHttpAdapter


def cycle(seq: int) -> dict:
    return {"seq": seq, "start": f"2026-10-05T09:{seq:02d}:00+00:00", "end": f"2026-10-05T09:{seq + 1:02d}:00+00:00",
            "records": [{"src": "A", "dst": "B", "cls": "web", "octets_fwd": 1000 * seq, "octets_rev": 10}]}


def test_flow_and_event_cursors_survive_a_source_restart():
    state = {"flows": [cycle(4), cycle(5)], "events": [{"seq": 7, "time": "2026-10-05T09:05:00+00:00",
                                                         "type": "link_down", "element": "A|B"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        after = int(request.url.params.get("after", 0))
        if request.url.path == "/v1/flows":
            latest = max((c["seq"] for c in state["flows"]), default=0)
            return httpx.Response(200, json={"latest": latest, "cycles": [c for c in state["flows"] if c["seq"] > after]})
        latest = max((e["seq"] for e in state["events"]), default=0)
        return httpx.Response(200, json={"latest": latest, "events": [e for e in state["events"] if e["seq"] > after]})

    adapter = TelemetryHttpAdapter("http://feed")
    transport = httpx.MockTransport(handler)
    adapter.client = httpx.Client(base_url="http://feed", transport=transport)
    adapter.event_client = httpx.Client(base_url="http://feed", transport=transport)

    assert adapter._flows() == ([], 0.0)              # first poll: only flows from now on (cursor 5)
    assert adapter.events(wait_seconds=0) == []       # first call: only events from now on (cursor 7)
    state["flows"].append(cycle(6))
    flows, seconds = adapter._flows()
    assert [f.octets_fwd for f in flows] == [6000] and seconds == 60

    # the source restarts: its numbering starts again, behind both cursors
    state["flows"] = [cycle(1)]
    state["events"] = [{"seq": 1, "time": "2026-10-05T10:00:00+00:00", "type": "link_up", "element": "A|B"}]
    flows, _ = adapter._flows()
    assert [f.octets_fwd for f in flows] == [1000]     # the new cycle is read, not skipped
    assert [e.type for e in adapter.events(wait_seconds=0)] == ["link_up"]
    state["flows"].append(cycle(2))
    assert [f.octets_fwd for f in adapter._flows()[0]] == [2000]   # and reading carries on normally
