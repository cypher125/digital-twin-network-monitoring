"""Local PostgreSQL for development tests and the offline fallback (plan section 12.2).

Runs an embedded PostgreSQL (the `pgserver` package) from var/localpg/data. The
main database is Neon; this is for fast local tests and for demos without internet.

    var/localpg/pgenv/Scripts/python deploy/localpg.py start              # prints the DATABASE_URL to use
    var/localpg/pgenv/Scripts/python deploy/localpg.py stop
    var/localpg/pgenv/Scripts/python deploy/localpg.py install-timezones  # once, after installing pgserver

The Windows build of pgserver ships without time-zone data, so PostgreSQL refuses to
start ("invalid value for parameter TimeZone: UTC"). install-timezones copies the IANA
time-zone files from the tzdata package (this environment's, or the backend's) into it.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "var" / "localpg" / "data"


def install_timezones() -> None:
    import pgserver

    target = Path(pgserver.__file__).parent / "pginstall" / "share" / "postgresql" / "timezone"
    if (target / "UTC").exists():
        print(f"time-zone data already present in {target}")
        return
    try:
        import tzdata
        source = Path(tzdata.__file__).parent / "zoneinfo"
    except ImportError:
        source = ROOT / "backend" / ".venv" / "Lib" / "site-packages" / "tzdata" / "zoneinfo"
    if not (source / "UTC").exists():
        sys.exit("No tzdata package found: install it with  uv pip install --python var/localpg/pgenv tzdata")
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__init__.py", "__pycache__"))
    print(f"copied time-zone data from {source} to {target}")


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    if action == "install-timezones":
        install_timezones()
        return
    import pgserver

    DATA.parent.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(DATA, cleanup_mode=None)  # keep running after this script exits
    if action == "stop":
        server.cleanup()
        print("stopped")
        return
    print(server.get_uri())


if __name__ == "__main__":
    main()
