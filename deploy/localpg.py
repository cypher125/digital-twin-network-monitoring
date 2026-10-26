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
import os
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("DT_LOCALPG_DATA", ROOT / "var" / "localpg" / "data"))
PORT_FILE = DATA.parent / f"{DATA.name}.port"


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pin_port() -> None:
    """pgserver picks a new random port at every start. Use the previous one again when it is free,
    so that programs already running (the engine, the API) find a restarted database again."""
    import pgserver.postgres_server as server_module

    try:
        port = int(PORT_FILE.read_text().strip())
    except (OSError, ValueError):
        return
    original = server_module.find_suitable_port

    def previous_port(address=None):
        return port if _port_is_free(port) else original(address)

    server_module.find_suitable_port = previous_port


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
    _pin_port()
    server = pgserver.get_server(DATA, cleanup_mode=None)  # keep running after this script exits
    if action == "stop":
        # server.cleanup() does nothing with cleanup_mode=None (the server is meant to outlive this
        # script), so it never stopped the database: stop it with pg_ctl (found by the E6 soak test)
        from pgserver._commands import pg_ctl

        pg_ctl(["-w", "-m", "fast", "stop"], pgdata=DATA)
        print("stopped")
        return
    uri = server.get_uri()
    port = uri.rsplit(":", 1)[-1].split("/", 1)[0]
    if port.isdigit():
        PORT_FILE.write_text(port)
    print(uri)


if __name__ == "__main__":
    main()
