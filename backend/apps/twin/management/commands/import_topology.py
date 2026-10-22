"""Import a topology file into the Topology Store (D1).

    python manage.py import_topology ../data/topologies/campus.yaml [--dry-run]
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.twin.topology_import import import_topology, read_topology_file
from digital_twin.runtime.persistence import bump_topology_generation


class Command(BaseCommand):
    help = "Import devices and links from a YAML or JSON topology file."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--dry-run", action="store_true", help="validate and report without saving")

    def handle(self, *args, **opts):
        report = import_topology(read_topology_file(opts["path"]), dry_run=opts["dry_run"])
        if not report.ok:
            raise CommandError("Import refused:\n  " + "\n  ".join(report.errors))
        verb = "Would import" if opts["dry_run"] else "Imported"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {report.devices_created} devices created, {report.devices_updated} updated; "
            f"{report.links_created} links created, {report.links_updated} updated."))
        for skipped in report.links_skipped:   # "A <-> B: not imported, because B is decommissioned"
            self.stdout.write(self.style.WARNING(f"{skipped}."))
        if opts["dry_run"]:
            return
        if not report.restart_needed:
            self.stdout.write("Only map positions changed (or nothing): no engine restart is needed.")
            return
        # Like an import through the dashboard: a running Digital Twin Engine reports that it
        # needs a restart to use the change (System page). Map positions alone need none.
        try:
            bump_topology_generation()
        except DatabaseError:
            # no runtime cache table yet (createcachetable has not run), so no engine is running either
            return
        self.stdout.write("A running Digital Twin Engine uses the changes once it is restarted.")
