#!/usr/bin/env python3
"""Turn a session tick log into a small, public test fixture.

    python3 tools/sim/make_fixture.py log/pi/shot-<ts>-tick.csv out.csv

Keeps only seconds since session start, the raw sensor reading and the heater
duty actually applied, in 1 s windows (heater time-averaged, so the energy is
preserved; sensor at the end of the window). No timestamps or other data.
"""
import csv
import math
import sys
from typing import List, Tuple


def downsample(path: str, window: float = 1.0) -> List[Tuple[float, float, float]]:
    rows = []
    with open(path, errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                rows.append((float(r["t"]), float(r["raw_temp"]), float(r["heater"])))
            except (TypeError, ValueError):
                continue  # NUL-padded tail of a power-cut session
    t0 = rows[0][0]
    out = [(0.0, rows[0][1], rows[0][2])]
    edge, energy = t0 + window, 0.0
    for (t, _temp, heater), (t_next, temp_next, _h) in zip(rows, rows[1:]):
        # heater[i] applies from t[i] until t[i+1]; split it across windows
        start = t
        while t_next > edge:
            energy += heater * (edge - start)
            out.append((round(edge - t0, 3), temp_next, energy / window))
            start, edge, energy = edge, edge + window, 0.0
        energy += heater * (t_next - start)
    return [r for r in out if all(math.isfinite(v) for v in r)]


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(dst, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "raw_temp", "heater"])
        for t, temp, heater in downsample(src):
            w.writerow([f"{t:.1f}", f"{temp:.3f}", f"{heater:.4f}"])
