#!/usr/bin/env python3
"""Summarize a captured shot log produced by espyresso.shot_logger.

Usage:
    python3 tools/review_shot.py log/shot-<ts>-tick.csv
    python3 tools/review_shot.py log/                      # picks newest pair

Reports warm-up, overshoot, steady-state error, heater-clip windows, brew
phases (from the event log), and per-phase MPC behaviour. Pure stdlib so it
runs on the Pi over SSH.
"""
import argparse
import csv
import glob
import math
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


def _read_ticks(path: str) -> Tuple[List[str], List[Dict[str, float]]]:
    rows: List[Dict[str, float]] = []
    with open(path) as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        for raw in reader:
            row: Dict[str, float] = {}
            for k, v in raw.items():
                if v == "" or v is None:
                    row[k] = math.nan
                    continue
                try:
                    row[k] = float(v)
                except ValueError:
                    # bool-as-int already handled; leave string fields out
                    pass
            rows.append(row)
    return cols, rows


def _read_events(path: str) -> List[Dict[str, str]]:
    events: List[Dict[str, str]] = []
    if not os.path.exists(path):
        return events
    with open(path) as f:
        next(f, None)  # header
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            t, kind, *rest = line.split(",", 2)
            details = rest[0] if rest else ""
            events.append({"t": t, "kind": kind, "details": details})
    return events


def _find_pair(arg: str) -> Tuple[str, str]:
    if os.path.isdir(arg):
        ticks = sorted(glob.glob(os.path.join(arg, "shot-*-tick.csv")))
        if not ticks:
            sys.exit(f"no shot-*-tick.csv files in {arg}")
        tick_path = ticks[-1]
    elif arg.endswith("-tick.csv"):
        tick_path = arg
    else:
        sys.exit(f"expected a directory or a *-tick.csv file, got {arg}")
    event_path = tick_path.replace("-tick.csv", "-event.csv")
    return tick_path, event_path


def _crossings(rows: List[Dict[str, float]], col: str, threshold: float) -> List[float]:
    """Times at which `col` crosses `threshold` (either direction)."""
    out: List[float] = []
    prev: Optional[float] = None
    for r in rows:
        v = r.get(col)
        if v is None or math.isnan(v):
            continue
        if prev is not None:
            if (prev < threshold) != (v < threshold):
                out.append(r["t"])
        prev = v
    return out


def _intervals_where(
    rows: List[Dict[str, float]], pred
) -> List[Tuple[float, float]]:
    """Return list of (start_t, end_t) intervals where pred(row) is true."""
    out: List[Tuple[float, float]] = []
    start: Optional[float] = None
    last_t: float = 0.0
    for r in rows:
        last_t = r["t"]
        if pred(r):
            if start is None:
                start = r["t"]
        else:
            if start is not None:
                out.append((start, r["t"]))
                start = None
    if start is not None:
        out.append((start, last_t))
    return out


def _stats(rows: List[Dict[str, float]], col: str) -> Tuple[float, float, float]:
    """min, max, mean of non-NaN values."""
    vals = [r[col] for r in rows if col in r and not math.isnan(r[col])]
    if not vals:
        return math.nan, math.nan, math.nan
    return min(vals), max(vals), sum(vals) / len(vals)


def summarize(tick_path: str, event_path: str) -> None:
    cols, rows = _read_ticks(tick_path)
    events = _read_events(event_path)
    if not rows:
        print("(empty tick log)")
        return

    duration = rows[-1]["t"] - rows[0]["t"]
    setpoint = next(
        (r["setpoint"] for r in rows if not math.isnan(r.get("setpoint", math.nan))),
        math.nan,
    )
    print(f"== file        : {tick_path}")
    print(f"== events file : {event_path}")
    print(f"== rows        : {len(rows)}")
    print(f"== duration    : {duration:.1f} s  ({duration/60:.2f} min)")
    print(f"== setpoint    : {setpoint:.2f} °C")
    avg_dt = duration / max(1, len(rows) - 1)
    print(f"== avg tick dt : {avg_dt*1000:.1f} ms  (~{1/avg_dt:.1f} Hz)")
    print()

    # warm-up: first time raw_temp reaches setpoint (or 95 if no setpoint).
    target = setpoint if not math.isnan(setpoint) else 95.0
    warmup_t: Optional[float] = None
    for r in rows:
        if not math.isnan(r.get("raw_temp", math.nan)) and r["raw_temp"] >= target:
            warmup_t = r["t"] - rows[0]["t"]
            break
    if warmup_t is not None:
        print(f"warm-up to {target:.1f} °C : {warmup_t:.1f} s")
    else:
        print(f"warm-up to {target:.1f} °C : never reached")

    # overshoot peak (raw sensor)
    rmin, rmax, _ = _stats(rows, "raw_temp")
    print(
        f"raw sensor range  : {rmin:.2f}–{rmax:.2f} °C   (peak overshoot vs setpoint: "
        f"{rmax - target:+.2f} °C)"
    )

    # heater clipping
    clipped_high = _intervals_where(rows, lambda r: r.get("heater", 0) >= 0.999)
    clipped_low_below_set = _intervals_where(
        rows,
        lambda r: r.get("heater", math.nan) <= 0.001
        and r.get("raw_temp", math.nan) < target - 1,
    )
    print(
        f"heater @ 100%     : {sum(b-a for a,b in clipped_high):.1f} s "
        f"({len(clipped_high)} intervals)"
    )
    print(
        f"heater @ 0% while temp < setpoint-1 °C : "
        f"{sum(b-a for a,b in clipped_low_below_set):.1f} s "
        f"({len(clipped_low_below_set)} intervals)"
    )

    # steady state band: ±0.5 °C around setpoint, after warm-up
    steady_band: List[Tuple[float, float]] = []
    if warmup_t is not None:
        steady_band = _intervals_where(
            rows,
            lambda r: r["t"] - rows[0]["t"] > (warmup_t or 0)
            and abs(r.get("raw_temp", math.nan) - target) < 0.5,
        )
    in_band_s = sum(b - a for a, b in steady_band)
    print(
        f"raw sensor within ±0.5 °C of setpoint : {in_band_s:.1f} s "
        f"({100*in_band_s/duration:.1f}% of run)"
    )

    # model steady-state flag activations
    steady_flag = _intervals_where(rows, lambda r: r.get("steadystate", 0) >= 0.5)
    steady_flag_s = sum(b - a for a, b in steady_flag)
    print(
        f"MPC steadystate=1 : {steady_flag_s:.1f} s "
        f"({len(steady_flag)} activations)"
    )

    # model vs sensor divergence (post-warmup)
    if warmup_t is not None and "modeledSensorTemp" in cols:
        diffs = [
            r["modeledSensorTemp"] - r["raw_temp"]
            for r in rows
            if r["t"] - rows[0]["t"] > (warmup_t or 0)
            and not math.isnan(r.get("modeledSensorTemp", math.nan))
            and not math.isnan(r.get("raw_temp", math.nan))
        ]
        if diffs:
            mn, mx = min(diffs), max(diffs)
            mean = sum(diffs) / len(diffs)
            print(
                f"modeledSensor − sensor (post-warmup): "
                f"mean {mean:+.2f}  range {mn:+.2f}…{mx:+.2f} °C"
            )

    # Brew phase summary from events
    if events:
        print()
        print("== events ==")
        for e in events:
            print(f"  t={float(e['t']):7.2f}  {e['kind']:14s}  {e['details']}")

    # Per-brew dive: between brew preinfuse_start and brew end
    brews = []
    cur_start: Optional[float] = None
    for e in events:
        if e["kind"] == "brew" and "phase=preinfuse_start" in e["details"]:
            cur_start = float(e["t"])
        elif e["kind"] == "brew" and "phase=end" in e["details"] and cur_start is not None:
            brews.append((cur_start, float(e["t"])))
            cur_start = None

    for i, (b0, b1) in enumerate(brews, 1):
        print(f"\n== brew #{i}: t={b0:.1f}…{b1:.1f} s ({b1-b0:.1f} s) ==")
        seg = [r for r in rows if b0 <= r["t"] - rows[0]["t"] <= b1]
        if not seg:
            print("  (no tick rows inside this brew window)")
            continue
        smin, smax, smean = _stats(seg, "raw_temp")
        bhmin, bhmax, bhmean = _stats(seg, "brewHeadTemp")
        wmin, wmax, wmean = _stats(seg, "waterTemp")
        hmin, hmax, hmean = _stats(seg, "heater")
        fmin, fmax, fmean = _stats(seg, "flow_rate")
        print(f"  sensor    : {smin:.1f}–{smax:.1f} °C   mean {smean:.2f}")
        print(f"  brewHead  : {bhmin:.1f}–{bhmax:.1f} °C   mean {bhmean:.2f}")
        print(f"  waterTemp : {wmin:.1f}–{wmax:.1f} °C   mean {wmean:.2f}")
        print(f"  heater    : {hmin:.2f}–{hmax:.2f}    mean {hmean:.2f}")
        print(f"  flow_rate : {fmin:.2f}–{fmax:.2f}    mean {fmean:.2f}")
        # Sensor temp at brew start vs end (proxy for boiler recovery)
        first_t = seg[0]["raw_temp"]
        last_t = seg[-1]["raw_temp"]
        print(f"  sensor Δ during brew : {last_t - first_t:+.2f} °C")


def main(argv: List[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "path",
        nargs="?",
        default="log/",
        help="path to a *-tick.csv file, or a directory containing them",
    )
    args = p.parse_args(argv)
    tick, event = _find_pair(args.path)
    summarize(tick, event)


if __name__ == "__main__":
    main(sys.argv[1:])
