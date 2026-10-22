"""Run the Digital Twin Engine (the monitoring cycle).

    python manage.py run_twin [--emulator http://127.0.0.1:9161]
"""
import signal

from django.conf import settings
from django.core.management.base import BaseCommand

from data_collection.network_adapter import TelemetryHttpAdapter
from digital_twin.runtime.engine import EngineSettings, TwinEngine


class Command(BaseCommand):
    help = "Run the Digital Twin Engine: collect, validate, update the twin and store, every cycle."

    def add_arguments(self, parser):
        parser.add_argument("--emulator", default=settings.TWIN["EMULATOR_URL"],
                            help="URL of the read-only telemetry feed")

    def handle(self, *args, **opts):
        adapter = TelemetryHttpAdapter(opts["emulator"])
        engine = TwinEngine(adapter, EngineSettings.from_django())

        def request_stop(*_):
            engine.stop.set()

        signal.signal(signal.SIGINT, request_stop)
        if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break, sent by the supervisor
            signal.signal(signal.SIGBREAK, request_stop)
        self.stdout.write(f"Digital Twin Engine reading {opts['emulator']} (Ctrl+C to stop)")
        try:
            engine.run_forever()
        finally:
            adapter.close()
