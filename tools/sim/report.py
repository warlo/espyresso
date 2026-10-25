#!/usr/bin/env python3
"""Closed-loop report: the production controller against the fitted plant.

    python3 tools/sim/report.py            # everything
    python3 tools/sim/report.py setpoints  # one section

Sections: precision, warmup, restarts, faults, shots, setpoints. Pure Python
(no numpy needed).
The boiler side is fitted to logs; puck numbers also depend on how much heat
the brew head takes from the water on its way to the coffee (eps), which no
sensor here measures. eps 0.55-0.7 reproduces a published thermocouple study
of a PID Classic (puck falling 7.5-10 C over a 60 mL shot); central 0.6, range
shown 0.5-0.7. The absolute puck level is less certain than that range (see
tools/sim/README.md).
"""
import contextlib
import logging
import math
import os
import sys
from typing import Callable, Dict, Iterator, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from espyresso import config  # noqa: E402
from espyresso.sim import closedloop, plant, scenarios  # noqa: E402

SP = config.TARGET_TEMP
GROUPS: Dict[str, Callable[[], Dict[str, float]]] = {
    "central": lambda: plant.fitted(),
    "eps 0.7": lambda: plant.fitted(eps=0.7),
    "eps 0.5": lambda: plant.fitted(eps=0.5),
}


def _fmt(v: float) -> str:
    return "  never" if math.isinf(v) else f"{v:7.1f}"


def _shot_stats(run: closedloop.Run, t0: float) -> Dict[str, float]:
    rows = [r for r in run.window(t0, t0 + scenarios.SHOT_SECONDS) if r["flow"] > 0]
    pucks = [r["puck"] for r in rows]
    cup = [r for r in rows if r["t"] >= t0 + scenarios.FILL_SECONDS]
    return dict(
        puck=sum(pucks) / len(pucks),
        drop=max(pucks) - min(pucks),
        # After the fill, weighted by flow: the water that reaches the cup.
        extraction=sum(r["puck"] * r["flow"] for r in cup) / sum(r["flow"] for r in cup),
        extraction_range=max(r["puck"] for r in cup) - min(r["puck"] for r in cup),
        water_min=min(r["water"] for r in rows),
        head=run.at(t0)["head"],
        head_model=run.at(t0)["m_head"],
        post_water=run.max("water", after=t0 + scenarios.SHOT_SECONDS),
        display_peak=run.max("sensor", after=t0),
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
    print("   scenario                      group     puck  drop  extraction  boiler min  head(true/model)  post water  display peak")
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
                f"   {name:29s} {group:8s} {s['puck']:5.1f} {s['drop']:5.1f}  {s['extraction']:5.1f}±{s['extraction_range'] / 2:3.1f}"
                f"   {s['water_min']:6.1f}"
                f"      {s['head']:5.1f}/{s['head_model']:5.1f}       {s['post_water']:5.1f}       {s['display_peak']:5.1f}"
            )
    first, second = 600.0, 600.0 + scenarios.SHOT_SECONDS + 23.0
    for budget in (True, False):
        run = closedloop.simulate(duration=900, start=plant.uniform(22.6), flow=scenarios.pi_shots([first, second], heat_budget=budget))
        a, b = _shot_stats(run, first), _shot_stats(run, second)
        print(f"   back-to-back (23 s apart), heat budget {budget!s:5s}: second shot {b['puck'] - a['puck']:+.2f} C vs first")


def setpoints() -> None:
    print("\n== setpoint -> puck temperature after the fill (what reaches the cup), Pi shot at 10 min (eps 0.6 / 0.7 / 0.5)")
    for sp in [93.0 + 0.5 * i for i in range(25)]:
        cells = []
        for group, params in GROUPS.items():
            run = closedloop.simulate(duration=720, start=plant.uniform(22.6), params=params(), setpoint=sp, flow=scenarios.pi_shots([600.0]))
            cells.append(_shot_stats(run, 600.0)["extraction"])
        idle = closedloop.simulate(duration=600, start=plant.uniform(22.6), setpoint=sp).window(500, 600)
        idle_water = sum(r["water"] for r in idle) / len(idle)
        print(f"   {sp:5.1f}: {cells[0]:5.1f} / {cells[1]:5.1f} / {cells[2]:5.1f}   idle boiler water {idle_water:5.1f}")


def _settled(run: closedloop.Run, target: float, band: float, after: float, hold: float = 60.0) -> float:
    """First time after ``after`` from which the boiler water stays within
    +-band of target for ``hold`` seconds."""
    rows = [r for r in run.rows if r["t"] >= after]
    for i, r in enumerate(rows):
        if abs(r["water"] - target) < band:
            j = i
            while j < len(rows) and abs(rows[j]["water"] - target) < band:
                if rows[j]["t"] - r["t"] >= hold:
                    return r["t"] - after
                j += 1
    return math.inf


def precision() -> None:
    """Precision of the boiler water by operating state (simulated; the
    sensor columns are what the display shows)."""
    print(f"== precision by state (setpoint {SP:.1f}, steam {config.TARGET_STEAM_TEMP:.0f}); times in s")
    print("   1. boot from cold")
    for t0 in (22.6, 35.5):
        run = closedloop.simulate(duration=900, start=plant.uniform(t0))
        reach = run.first_time(lambda r: r["sensor"] >= SP - 0.5)
        print(
            f"      from {t0:4.1f} C: display at setpoint {reach:5.0f} | water within 1 C {_fmt(run.first_time(lambda r: abs(r['water'] - SP) < 1.0))}"
            f" | settled +-0.5 C {_fmt(_settled(run, SP, 0.5, 0))} | water peak {run.max('water') - SP:+.2f} | display peak {run.max('sensor') - SP:+.2f}"
        )
    print("   2. maintaining (10-25 min after a cold boot)")
    run = closedloop.simulate(duration=1500, start=plant.uniform(22.6))
    idle = run.window(600, 1500)
    for col, name in (("water", "water  "), ("sensor", "display")):
        vals = [r[col] - SP for r in idle]
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        print(f"      {name}: mean {mean:+.2f} C, sd {sd:.3f} C, range {min(vals):+.2f}..{max(vals):+.2f}")
    print("   3. brewing (shot at 10 min; puck = central eps 0.6, range eps 0.7..0.5)")
    for name, flow in (("Pi shot   ", scenarios.pi_shots([600.0])), ("manual    ", scenarios.manual_shots([600.0]))):
        pucks = {}
        for group, params in GROUPS.items():
            r = closedloop.simulate(duration=1000, start=plant.uniform(22.6), params=params(), flow=flow)
            pucks[group] = _shot_stats(r, 600.0)
            if group == "central":
                run = r
        s = pucks["central"]
        end = 600.0 + scenarios.SHOT_SECONDS
        print(
            f"      {name}: boiler water {run.at(600)['water']:.1f} -> min {s['water_min']:.1f} | puck {s['puck']:.1f} C"
            f" ({pucks['eps 0.7']['puck']:.1f}..{pucks['eps 0.5']['puck']:.1f}), drop over shot {s['drop']:.1f} C"
            f" | after the fill {s['extraction']:.1f} C ({pucks['eps 0.7']['extraction']:.1f}..{pucks['eps 0.5']['extraction']:.1f})"
            f" range {s['extraction_range']:.1f}"
            f" | back within +-0.5 C {_fmt(_settled(run, SP, 0.5, end))} after | post-shot water peak {s['post_water'] - SP:+.2f}"
        )
    first, second = 600.0, 600.0 + scenarios.SHOT_SECONDS + 23.0
    run = closedloop.simulate(duration=900, start=plant.uniform(22.6), flow=scenarios.pi_shots([first, second]))
    print(f"      back-to-back Pi shots 23 s apart: second {_shot_stats(run, second)['puck'] - _shot_stats(run, first)['puck']:+.2f} C at the puck")
    print("   4. steaming (Pi steam mode from idle at 10 min, 120 s, no refill; steam draw not modelled)")
    st = config.TARGET_STEAM_TEMP
    run = closedloop.simulate(duration=600 + 120 + 1500, start=plant.uniform(22.6), flow=scenarios.steam(600.0, 120.0, refill_flow=0.0))
    print(
        f"      display at {st - 1:.0f} C after {run.first_time(lambda r: r['t'] > 600 and r['sensor'] >= st - 1) - 600:.0f}"
        f" | water after 60 s {run.at(660)['water']:.1f}, after 120 s {run.at(720)['water']:.1f} | display peak {run.max('sensor', after=600, before=720):.1f}"
        f" | back to brew +-1 C {_fmt(run.first_time(lambda r: r['t'] > 720 and abs(r['water'] - SP) < 1.0) - 720)} after steam ends"
    )


@contextlib.contextmanager
def _warmup_off() -> Iterator[None]:
    saved = config.WARMUP_MAX_OFFSET
    config.WARMUP_MAX_OFFSET = 0.0
    try:
        yield
    finally:
        config.WARMUP_MAX_OFFSET = saved


WARMUP_SHOTS = (3, 4, 5, 6, 7, 8, 10)


def warmup() -> None:
    """How soon after a cold start a shot matches one from a warm machine,
    with and without the warm-up, on every plant that fits the logs and on
    stress cases outside them."""
    fit = plant.fitted()
    plants = dict(plant.candidates())
    plants["stress: 1240 W element"] = plant.fitted(P_max=1240.0)
    plants["stress: group coupling x0.6"] = plant.fitted(k_bh=fit["k_bh"] * 0.6)
    plants["stress: group coupling x1.5"] = plant.fitted(k_bh=fit["k_bh"] * 1.5)

    def puck(params: Dict[str, float], at: float, preheat: bool = False) -> float:
        flow = scenarios.preheat_then_shot(90.0, at) if preheat else scenarios.pi_shots([at])
        run = closedloop.simulate(duration=at + 60, start=plant.uniform(22.6), params=params, flow=flow, auto_off=False)
        return _shot_stats(run, at)["puck"]

    def ready(errors: List[float], tolerance: float) -> float:
        for i in range(len(WARMUP_SHOTS)):
            if all(abs(e) <= tolerance for e in errors[i:]):
                return WARMUP_SHOTS[i]
        return math.inf

    def ready_at(run: closedloop.Run) -> float:
        since = math.inf
        for r in run.rows:
            since = (since if since < math.inf else r["t"]) if r["state"] == "READY" else math.inf
        return since / 60

    print(f"\n== warm-up: Pi shot after a cold start minus a warm machine's shot (C); setpoint {SP:.1f}")
    print("   shot at (min)          " + " ".join(f"{m:>5d}" for m in WARMUP_SHOTS)
          + "  | within 1 / 0.5 C from (min) | display peak | flush@1.5, shot@5 | screen READY at (min)")
    for name, params in plants.items():
        warm = puck(params, 2400.0)
        print(f"   {name}")
        for label, ctx in (("now", contextlib.nullcontext), ("no warm-up", _warmup_off)):
            with ctx():
                errors = [puck(params, m * 60.0) - warm for m in WARMUP_SHOTS]
                flushed = puck(params, 300.0, preheat=True) - warm
                run = closedloop.simulate(duration=900, start=plant.uniform(22.6), params=params, auto_off=False)
                flush_run = closedloop.simulate(
                    duration=900, start=plant.uniform(22.6), params=params,
                    flow=scenarios.preheat_then_shot(90.0, 10_000.0), auto_off=False,
                )
            off = [r["t"] for r in run.rows if r["target"] > SP]
            ends = f", warm-up off at {off[-1] / 60:4.1f} min" if off else ""
            print(
                f"     {label:20s} " + " ".join(f"{e:+5.1f}" for e in errors)
                + f"  | {_fmt(ready(errors, 1.0))} / {_fmt(ready(errors, 0.5))}       | {run.max('sensor') - SP:+5.1f}       | {flushed:+5.1f}"
                + f"             | {ready_at(run):4.1f} ({ready_at(flush_run):4.1f} with flush){ends}"
            )


SECTIONS = dict(precision=precision, warmup=warmup, restarts=restarts, faults=faults, shots=shots, setpoints=setpoints)

if __name__ == "__main__":
    # The fault scenarios trip the real safety code, which logs loudly.
    logging.disable(logging.CRITICAL)
    for name in sys.argv[1:] or list(SECTIONS):
        SECTIONS[name]()
