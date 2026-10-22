"""Run the emulator offline and summarise link utilisation, to check the traffic model.

    python -m netemu.calibrate --days 7 [--start 2026-10-05T00:00:00+01:00] [--no-faults]

Prints, per link: mean, 95th percentile and peak utilisation (cycle averages),
the hour of day when the peak occurred, and how many cycles were at or above
70 % and 90 %.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime

import numpy as np

from .__main__ import DEFAULT_TOPOLOGY
from .network import EmulatedNetwork
from .topology import load_topology
from .traffic import WAT


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="netemu.calibrate")
    p.add_argument("--topology", default=str(DEFAULT_TOPOLOGY))
    p.add_argument("--days", type=float, default=7)
    p.add_argument("--start", default="2026-10-05T00:00:00+01:00")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--no-faults", action="store_true")
    args = p.parse_args(argv)

    topo = load_topology(args.topology)
    net = EmulatedNetwork(topo, datetime.fromisoformat(args.start), seed=args.seed,
                          history_cycles=int(args.days * 1440) + 10)
    net.random_faults = not args.no_faults
    cycles = int(args.days * 1440)
    began = time.perf_counter()
    for _ in range(cycles * net.steps_per_cycle()):
        net.step()
    elapsed = time.perf_counter() - began

    util = np.array([[lk["utilisation_pct"] for lk in c["links"]] for c in net.truth])
    hours = np.array([datetime.fromisoformat(c["end"]).astimezone(WAT).hour for c in net.truth])
    print(f"{cycles} cycles ({args.days} days) in {elapsed:.1f} s "
          f"({elapsed / cycles * 1000:.2f} ms per cycle); events: {net.event_seq}")
    print(f"{'link':34s} {'cap':>6s} {'mean':>6s} {'p95':>6s} {'peak':>6s} {'@h':>3s} {'>=70':>6s} {'>=90':>6s}")
    order = np.argsort(-util.max(axis=0))
    for i in order:
        lk = net.links[i]
        col = util[:, i]
        peak_at = int(hours[int(col.argmax())])
        print(f"{lk.a + ' - ' + lk.b:34s} {lk.capacity_mbps:6.0f} {col.mean():6.1f} "
              f"{np.percentile(col, 95):6.1f} {col.max():6.1f} {peak_at:3d} "
              f"{int((col >= 70).sum()):6d} {int((col >= 90).sum()):6d}")


if __name__ == "__main__":
    main()
