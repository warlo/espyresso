#!/usr/bin/env python3
"""Fit the simulator's plant to logged cold starts.

    uv run --with pandas --with numpy --with scipy python tools/sim/fit.py [--write]

Replays the logged heater command through the plant (no controller, no sensor
correction) and fits the coefficients so the plant's sensor matches the logged
sensor. Uses every session in log/pi that starts cold (< 40 C) with the boiler
on for most of the run. ``--write`` saves espyresso/sim/plant_fit.json; then
run the regression tests and tools/sim/report.py.

Logs from before the self-healing controller (no ``heater_cmd`` column) had
~5-7 s of blind full power before the first tick when booting with the boiler
on; it is reconstructed from the first tick's deltaTime.

The boiler shell and water volume are fixed at Tom Brazier's weighed values
by default: the aluminium Classic and his Baby share the boiler (EF0030/A) and
group (B0171). Fixing them sets the model's scale; without it the fit can
trade every heat capacity, coupling and the heater power against each other
(scaling all of them together leaves the temperatures unchanged) and drifts.
``--free-masses`` fits them anyway.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)

from espyresso.sim.plant import FIT_PATH, nominal, replay_sensor  # noqa: E402

# name, lower, upper (multipliers of the controller's constant, a_s absolute),
# prior sigma in log units (None = free). Power and the group's coupling are
# known roughly (element rating, Tom's measurement), so they get loose priors.
SPEC = [
    ("P_max", 0.80, 1.15, 0.07),
    ("k_es", 0.2, 5.0, None),
    ("k_w", 0.2, 5.0, None),
    ("k_bh", 0.3, 3.0, 0.3),
    ("k_body", 0.2, 5.0, None),
    ("C_body", 0.2, 5.0, 0.5),
    ("k_s", 0.1, 20.0, None),
    ("a_s", 0.0, 1.0, None),
]
MASS_SPEC = [("m_shell", 0.6, 2.5, 0.3), ("V", 0.7, 1.6, 0.2)]


def load_sessions(log_dir):
    sessions = {}
    for path in sorted(glob.glob(os.path.join(log_dir, "shot-*-tick.csv"))):
        df = pd.read_csv(path, low_memory=False).apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["t", "raw_temp", "heater"]).reset_index(drop=True)
        if len(df) < 600 or df["raw_temp"].iloc[0] > 40 or df["boiling"].mean() < 0.8:
            continue
        t, T, u = df["t"].to_numpy(), df["raw_temp"].to_numpy(), df["heater"].to_numpy()
        if "heater_cmd" not in df.columns and df["boiling"].iloc[0] == 1 and u[0] >= 0.99:
            blind = float(df["deltaTime"].iloc[0])
            t, T, u = np.r_[t[0] - blind, t], np.r_[T[0], T], np.r_[1.0, u]
        sessions[os.path.basename(path)[5:20]] = (t, T, u)
    return sessions


def replay(p, t, u, T0):
    return np.asarray(replay_sensor(p, t, u, T0))


def unpack(x, base):
    p = dict(base)
    for (name, _lo, _hi, _sig), v in zip(SPEC, x):
        p[name] = v if name == "a_s" else base[name] * v
    return p


def residuals(x, base, sessions, stride=5):
    p = unpack(x, base)
    res = [(replay(p, t, u, T[0]) - T)[::stride] for t, T, u in sessions.values()]
    res += [np.array([np.log(v) / sig * 3.0]) for (_n, _l, _h, sig), v in zip(SPEC, x) if sig]
    return np.concatenate(res)


def report(p, sessions, label):
    print(f"== {label}")
    for name, (t, T, u) in sessions.items():
        err = replay(p, t, u, T[0]) - T
        hot = T > 80
        print(f"   {name}: RMSE {np.sqrt(np.mean(err ** 2)):5.2f} C, above 80 C bias {err[hot].mean():+5.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", default=os.path.join(ROOT, "log", "pi"))
    ap.add_argument("--write", action="store_true", help="save espyresso/sim/plant_fit.json")
    ap.add_argument("--free-masses", action="store_true", help="also fit shell mass and water volume")
    args = ap.parse_args()
    if args.free_masses:
        SPEC[1:1] = MASS_SPEC

    sessions = load_sessions(args.logs)
    if not sessions:
        sys.exit(f"no cold-start sessions in {args.logs}")
    base = nominal()
    report(base, sessions, "controller's own constants, open loop")

    x0 = np.array([1.0] * (len(SPEC) - 1) + [0.99])
    bounds = (np.array([s[1] for s in SPEC]), np.array([s[2] for s in SPEC]))
    fit = least_squares(residuals, x0, args=(base, sessions), bounds=bounds, diff_step=1e-3, max_nfev=300)
    p = unpack(fit.x, base)
    report(p, sessions, "fitted plant")
    at_bounds = []
    for (name, lo, hi, _sig), v in zip(SPEC, fit.x):
        flag = ""
        if v <= lo * 1.01 or v >= hi * 0.99:
            flag = "  <- at its bound"
            at_bounds.append(name)
        print(f"   {name:8s} {base[name]:10.4f} -> {p[name]:10.4f}{flag}")
    if at_bounds:
        print(
            f"WARNING: {', '.join(at_bounds)} at their bounds: the plant can't explain these "
            "sessions with plausible physics (e.g. a non-uniform start). Check before --write."
        )

    if len(sessions) > 1:
        print("== leave-one-out (fit without a session, predict it)")
        for held in sessions:
            rest = {k: v for k, v in sessions.items() if k != held}
            f = least_squares(residuals, x0, args=(base, rest), bounds=bounds, diff_step=1e-3, max_nfev=300)
            t, T, u = sessions[held]
            err = replay(unpack(f.x, base), t, u, T[0]) - T
            print(f"   {held}: RMSE {np.sqrt(np.mean(err ** 2)):.2f} C, above 80 C bias {err[T > 80].mean():+.2f}")

    if args.write:
        with open(FIT_PATH, "w") as fh:
            json.dump(p, fh, indent=1)
        print(f"wrote {FIT_PATH}")


if __name__ == "__main__":
    main()
