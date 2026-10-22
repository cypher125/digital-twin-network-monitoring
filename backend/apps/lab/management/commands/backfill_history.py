"""Fill the database with history from the emulator (plan decision D20).

The emulator must be running in stepped mode, started at the first day of the
history, for example:

    python -m netemu serve --mode stepped --start 2026-10-04T00:00:00+01:00
    python manage.py backfill_history --days 14 --then-live --speed 20

The test harness steps the emulator's clock through its lab interface, one
cycle at a time. Every cycle is then read through the twin's normal pipeline:
the same read-only adapter, the same preprocessing, the same network model.
So the training history is genuinely twin-collected data.
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction

from apps.twin.models import MonitoringRecord
from data_collection.network_adapter import TelemetryHttpAdapter
from data_collection.preprocessing import Preprocessor
from digital_twin.runtime import persistence
from evaluation.lab_client import LabClient

COPY_COLUMNS = ("device_id", "link_id", "timestamp", "traffic_in", "traffic_out", "utilisation_pct",
                "error_count", "cpu_util", "status", "received_at")


def copy_records(rows: list[MonitoringRecord]) -> None:
    """Fast bulk load with PostgreSQL COPY (used for fresh history; falls back on conflicts)."""
    with connection.cursor() as cursor, cursor.cursor.copy(
            f"COPY monitoring_record ({', '.join(COPY_COLUMNS)}) FROM STDIN") as copy:
        for r in rows:
            copy.write_row((r.device_id, r.link_id, r.timestamp, r.traffic_in, r.traffic_out,
                            r.utilisation_pct, r.error_count, r.cpu_util, r.status, r.received_at))


class Command(BaseCommand):
    help = "Generate history by stepping the emulator and passing every cycle through the twin's pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=14)
        parser.add_argument("--emulator", default=settings.TWIN["EMULATOR_URL"])
        parser.add_argument("--lab-token", help="default: NETEMU_LAB_TOKEN or var/netemu/lab_token")
        parser.add_argument("--flush-cycles", type=int, default=60, help="cycles per database write")
        parser.add_argument("--then-live", action="store_true", help="switch the emulator to live mode at the end")
        parser.add_argument("--speed", type=float, default=1.0, help="live speed after the backfill")

    def handle(self, *args, **opts):
        lab = LabClient(opts["emulator"], opts["lab_token"])
        adapter = TelemetryHttpAdapter(opts["emulator"], flows_from_now=True)
        twin = settings.TWIN
        cycle_seconds = twin["CYCLE_SECONDS"]
        info = lab.info()
        if info["cycle_seconds"] != cycle_seconds:
            raise CommandError(f"emulator cycle is {info['cycle_seconds']} s but CYCLE_SECONDS is {cycle_seconds} s")
        if info["mode"] != "stepped":
            lab.mode("stepped")
        index, model = persistence.build_model(twin["WARNING_THRESHOLD_PCT"], twin["CRITICAL_THRESHOLD_PCT"],
                                               twin["REFERENCE_BANDWIDTH_MBPS"])
        if not index.devices:
            raise CommandError("the Topology Store is empty: run `manage.py import_topology` first")
        latest = persistence.latest_timestamp()
        pre = Preprocessor(index, cycle_seconds, last_timestamp=latest)
        total = int(opts["days"] * 86400 / cycle_seconds)
        self.stdout.write(f"Backfilling {total} cycles from emulator time {info['time']} "
                          f"(database latest: {latest or 'empty'})")

        lab.step(1)
        pre.process(adapter.poll())          # baseline counters; the first poll has no rates
        buffer: list[MonitoringRecord] = []
        last_status: dict[tuple[str, int], object] = {}
        began, stored, use_copy = time.perf_counter(), 0, True

        def flush():
            nonlocal stored, use_copy
            if not buffer and not last_status:
                return
            try:
                with transaction.atomic():
                    if use_copy:
                        copy_records(buffer)
                    else:
                        persistence.write_records(buffer)
                    persistence.write_status_changes(list(last_status.values()))
            except DatabaseError:
                if not use_copy:
                    raise
                use_copy = False                 # e.g. overlapping history: insert row by row instead
                with transaction.atomic():
                    persistence.write_records(buffer)
                    persistence.write_status_changes(list(last_status.values()))
            stored += len(buffer)
            buffer.clear()
            last_status.clear()

        for i in range(1, total + 1):
            lab.step(1)
            clean = pre.process(adapter.poll())
            if clean is None:
                continue
            for change in model.apply(clean):
                last_status[(change.kind, change.element_id)] = change
            buffer.extend(persistence.records_for(clean))
            if i % opts["flush_cycles"] == 0:
                flush()
            if i % (86400 // cycle_seconds) == 0 or i == total:
                elapsed = time.perf_counter() - began
                eta = elapsed / i * (total - i)
                self.stdout.write(f"  {clean.timestamp:%Y-%m-%d %H:%M} UTC: {i}/{total} cycles, "
                                  f"{stored + len(buffer)} rows, {elapsed / 60:.1f} min elapsed, "
                                  f"about {eta / 60:.1f} min left")
        flush()
        adapter.close()
        if opts["then_live"]:
            lab.mode("live", speed=opts["speed"], catch_up=opts["speed"] == 1.0)
        lab.close()
        self.stdout.write(self.style.SUCCESS(
            f"Stored {stored} monitoring records in {(time.perf_counter() - began) / 60:.1f} min."))
