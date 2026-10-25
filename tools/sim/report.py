#!/usr/bin/env python3
"""Closed-loop report: the production controller against the fitted plant.

    python3 tools/sim/report.py            # everything
    python3 tools/sim/report.py setpoints  # one section

Sections: restarts, faults, shots, setpoints. Pure Python (no numpy needed).
The boiler side is fitted to logs; puck numbers depend on the group's
coupling, which no sensor measures, so they are shown for three assumptions:
central (eps 0.5), weak (group barely heated by the boiler) and strong.
"""
import logging
import math
import os
import sys
from typing import Callable, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from espyresso import config  # noqa: E402
from espyresso.sim import closedloop, plant, scenarios  # noqa: E402

SP = config.TARGET_TEMP
GROUPS: Dict[str, Callable[[], Dict[str, float]]] = {
    "central": lambda: plant.fitted(),
    "weak": lambda: plant.fitted(eps=1.0, k_bh=plant.fitted()["k_bh"] * 0.5),
    "strong": lambda: plant.fitted(eps=0.25, k_bh=plant.fitted()["k_bh"] * 2.0),
}


def _fmt(v: float) -> str:
    return "  never" if math.isinf(v) else f"{v:7.1f}"


def _shot_stats(run: closedloop.Run, t0: float) -> Dict[str, float]:
    rows = [r for r in run.window(t0, t0 + scenarios.SHOT_SECONDS) if r["flow"] > 0]
    pucks = [r["puck"] for r in rows]
    return dict(
        puck=sum(pucks) / len(pucks),
        drop=max(pucks) - min(pucks),
        water_min=min(r["water"] for r in rows),
        head=run.at(t0)["head"],
        head_model=run.at(t0)["m_head"],
        post_water=run.max("water", after=t0 + scenarios.SHOT_SECONDS),
        post_sensor=run.max("sensor", after=t0 + scenarios.SHOT_SECONDS),
    )


def restarts() -> None:
    print(f"== restarts (setpoint {SP:.1f}): app starts with the machine in this state")
    print("   start            water within 1C   water peak   sensor peak")
    starts = {
        "cold 22": plant.uniform(22.6),
        "lukewarm 60": plant.uniform(60.0, head=50.0, body=50.0),
        "warm 80": plant.uniform(80.0, head=72.0, body=70.0),
        "warm 90": plant.uniform(90.0, head=80.0, body=78.0),
        "at setpoint": plant.at_setpoint(SP),
        "hot +7": plant.at_setpoint(SP + 7),
        "after crash": dict(elem=SP + 30.0, shell=SP + 10.0, water=SP + 2.0, body=82.0, head=SP - 9.0, sensor=SP + 3.0),
    }
    for name, start in starts.items():
        run = closedloop.simulate(duration=600, start=start)
        t = run.first_time(lambda r: abs(r["water"] - SP) < 1.0)
        print(f"   {name:15s} {_fmt(t)} s         {run.max('water'):7.2f}      {run.max('sensor'):7.2f}")


def faults() -> None:
    print("\n== faults")
    run = closedloop.simulate(duration=500, start=plant.uniform(60.0), stall=(100.0, 130.0))
    off = all(r["duty"] == 0 for r in run.window(100 + config.CONTROL_STALE_SECONDS + 0.6, 130))
    print(f"   30 s control stall at 60C: heater off during stall {off}; water peak after {run.max('water', after=130):.2f}")
    run = closedloop.simulate(duration=300, start=plant.at_setpoint(SP), first_reading_ok=False)
    print(f"   failed first reading at setpoint: water peak {run.max('water'):.2f}")
    run = closedloop.simulate(duration=150, start=plant.uniform(22.6), sensor_override=lambda t, true: 22.6)
    t_off = next((r["t"] for r in run.rows if r["t"] > 10 and r["duty"] == 0), math.inf)
    print(f"   detached sensor (reads 22.6) from cold: heater off at {t_off:.0f} s; water reached {run.max('water'):.1f}")


def shots() -> None:
    print(f"\n== shots (setpoint {SP:.1f}); puck = water reaching the coffee")
    print("   scenario                      group     puck  drop  boiler min  head(true/model)  post water/sensor")
    cases = [
        ("Pi shot at 10 min", lambda: scenarios.pi_shots([600.0]), [600.0]),
        ("same, no heat budget", lambda: scenarios.pi_shots([600.0], heat_budget=False), [600.0]),
        ("manual shot at 10 min", lambda: scenarios.manual_shots([600.0]), [600.0]),
        ("preheat 1.5 min, shot 7 min", lambda: scenarios.preheat_then_shot(90.0, 420.0), [420.0]),
        ("preheat 1.5 min, shot 20 min", lambda: scenarios.preheat_then_shot(90.0, 1200.0), [1200.0]),
    ]
    for name, flow, starts in cases:
        for group, params in GROUPS.items():
            run = closedloop.simulate(duration=starts[-1] + 120, start=plant.uniform(22.6), params=params(), flow=flow())
            s = _shot_stats(run, starts[-1])
            print(
                f"   {name:29s} {group:8s} {s['puck']:5.1f} {s['drop']:5.1f}   {s['water_min']:6.1f}"
                f"      {s['head']:5.1f}/{s['head_model']:5.1f}       {s['post_water']:5.1f}/{s['post_sensor']:5.1f}"
            )
    first, second = 600.0, 600.0 + scenarios.SHOT_SECONDS + 23.0
    for budget in (True, False):
        run = closedloop.simulate(duration=900, start=plant.uniform(22.6), flow=scenarios.pi_shots([first, second], heat_budget=budget))
        a, b = _shot_stats(run, first), _shot_stats(run, second)
        print(f"   back-to-back (23 s apart), heat budget {budget!s:5s}: second shot {b['puck'] - a['puck']:+.2f} C vs first")


def setpoints() -> None:
    print("\n== setpoint -> mean puck temperature, Pi shot at 10 min (central / weak / strong group)")
    for sp in [93.0 + 0.5 * i for i in range(17)]:
        cells = []
        for group, params in GROUPS.items():
            run = closedloop.simulate(duration=720, start=plant.uniform(22.6), params=params(), setpoint=sp, flow=scenarios.pi_shots([600.0]))
            cells.append(_shot_stats(run, 600.0)["puck"])
        idle = closedloop.simulate(duration=600, start=plant.uniform(22.6), setpoint=sp).window(500, 600)
        idle_water = sum(r["water"] for r in idle) / len(idle)
        print(f"   {sp:5.1f}: {cells[0]:5.1f} / {cells[1]:5.1f} / {cells[2]:5.1f}   idle boiler water {idle_water:5.1f}")


SECTIONS = dict(restarts=restarts, faults=faults, shots=shots, setpoints=setpoints)

if __name__ == "__main__":
    # The fault scenarios trip the real safety code, which logs loudly.
    logging.disable(logging.CRITICAL)
    for name in sys.argv[1:] or list(SECTIONS):
        SECTIONS[name]()
