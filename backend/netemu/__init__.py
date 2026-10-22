"""Network emulator: the stand-in for the real network (write-up section 3.6).

It carries simulated traffic over a campus topology and exposes what real
equipment would: SNMP-style interface counters, aggregated flow telemetry and
up/down events. The digital twin reads it only through its read-only feed.

This package must not import anything from the digital twin (enforced by
import-linter), so the twin cannot share code or assumptions with its data source.
"""
