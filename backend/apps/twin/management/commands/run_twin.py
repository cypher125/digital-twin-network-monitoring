"""Run the Digital Twin Engine (the monitoring cycle).

    python manage.py run_twin [--adapter telemetry-http] [--emulator http://127.0.0.1:9161]
"""
import signal

from django.conf import settings
from django.core.management.base import BaseCommand

from data_collection.network_adapter import ADAPTERS, make_adapter
from digital_twin.runtime.engine import EngineSettings, TwinEngine


class Command(BaseCommand):
    help = "Run the Digital Twin Engine: collect, validate, update the twin and store, every cycle."

    def add_arguments(self, parser):
        parser.add_argument("--adapter", default="telemetry-http", choices=sorted(ADAPTERS),
                            help="which network adapter reads the data source")
        parser.add_argument("--emulator", "--source", dest="emulator", default=settings.TWIN["EMULATOR_URL"],
                            help="address of the read-only data source (for telemetry-http, the feed URL)")

    def handle(self, *args, **opts):
        adapter = make_adapter(opts["adapter"], opts["emulator"])
        engine = TwinEngine(adapter, EngineSettings.from_django())

        def request_stop(*_):
            engine.stop.set()

        signal.signal(signal.SIGINT, request_stop)
        if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break, sent by the supervisor
            signal.signal(signal.SIGBREAK, request_stop)
        self.stdout.write(f"Digital Twin Engine reading {opts['emulator']} with the {opts['adapter']} adapter "
                          "(Ctrl+C to stop)")
        try:
            engine.run_forever()
        finally:
            adapter.close()
