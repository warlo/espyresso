"""Closed-loop regression tests: the production control path (Temperature,
PController, SafetyGuard, Boiler, Watchdog) against the plant fitted to this
machine's logs (espyresso/sim). Each test pins a behaviour that was wrong
before, so tuning can't silently bring it back.

The plant is only as good as the logs it was fitted to (two cold starts;
cross-validated to about +-2.5 C). Boiler-side behaviour is the trustworthy
part; puck temperatures depend on unmeasured group coupling, so they are
compared relative to each other, not asserted as absolute truths.
"""

from __future__ import annotations

import pytest

from espyresso import config
from espyresso.sim import closedloop, plant, scenarios

SP = config.TARGET_TEMP


def test_cold_start_reaches_setpoint_without_large_overshoot() -> None:
    run = closedloop.simulate(duration=360, start=plant.uniform(22.6))

    assert run.first_time(lambda r: abs(r["water"] - SP) < 1.0) < 240
    assert run.max("water") < SP + 2.0


def test_restart_at_setpoint_does_not_overshoot() -> None:
    # The old blind 6 s boot boost pushed the water to setpoint + 4.3 C here.
    run = closedloop.simulate(duration=240, start=plant.at_setpoint(SP))

    assert run.max("water") < SP + 1.0


def test_restart_15_below_setpoint_heats_quickly_without_overshoot() -> None:
    # e.g. a reboot at 80 C with a 95 C setpoint
    run = closedloop.simulate(duration=300, start=plant.uniform(SP - 15.0, head=SP - 23.0, body=SP - 25.0))

    assert run.first_time(lambda r: abs(r["water"] - SP) < 1.0) < 110
    assert run.max("water") < SP + 1.5


def test_hot_start_after_crash_heals() -> None:
    # Element left on while the Pi was frozen.
    start = dict(elem=SP + 30.0, shell=SP + 10.0, water=SP + 2.0, body=82.0, head=SP - 9.0, sensor=SP + 3.0)
    run = closedloop.simulate(duration=600, start=start)

    assert abs(run.at(600)["water"] - SP) < 1.0


def test_control_stall_turns_heater_off_and_recovers() -> None:
    run = closedloop.simulate(duration=500, start=plant.uniform(60.0), stall=(100.0, 130.0))

    during = run.window(100.0 + config.CONTROL_STALE_SECONDS + 0.6, 130.0)
    assert during and all(r["duty"] == 0 for r in during)
    # No model blow-up after the 30 s gap (it used to reach -59 C and pin 100 %).
    assert run.max("water", after=130.0) < SP + 2.0
    assert abs(run.at(500)["water"] - SP) < 1.0


def test_failed_first_reading_does_not_heat_blind() -> None:
    run = closedloop.simulate(duration=240, start=plant.at_setpoint(SP), first_reading_ok=False)

    assert run.max("water") < SP + 1.0


def test_detached_sensor_switches_heater_off() -> None:
    run = closedloop.simulate(
        duration=120, start=plant.uniform(22.6), sensor_override=lambda t, true: 22.6
    )

    late = run.window(config.SAFETY_RUNAWAY_SECONDS + 3, 120)
    assert late and all(r["duty"] == 0 for r in late)


def _pi_shot(horizon: bool) -> closedloop.Run:
    flow = scenarios.pi_shots([600.0], heat_budget=horizon)
    return closedloop.simulate(duration=800, start=plant.uniform(22.6), flow=flow)


def test_heat_budget_narrows_in_shot_drop_without_post_shot_overshoot() -> None:
    with_budget, without = _pi_shot(True), _pi_shot(False)
    end = 600.0 + scenarios.SHOT_SECONDS

    def spread(run: closedloop.Run) -> float:
        pucks = [r["puck"] for r in run.window(600.0, end) if r["flow"] > 0]
        return max(pucks) - min(pucks)

    assert spread(with_budget) < spread(without) - 0.5
    assert with_budget.max("water", after=end) < SP + 1.5


def test_back_to_back_pi_shots_stay_within_one_degree() -> None:
    first, second = 600.0, 600.0 + scenarios.SHOT_SECONDS + 23.0
    run = closedloop.simulate(duration=800, start=plant.uniform(22.6), flow=scenarios.pi_shots([first, second]))

    def mean_puck(t0: float) -> float:
        pucks = [r["puck"] for r in run.window(t0, t0 + scenarios.SHOT_SECONDS) if r["flow"] > 0]
        return sum(pucks) / len(pucks)

    assert abs(mean_puck(second) - mean_puck(first)) < 1.0


def test_simulated_session_writes_pi_format_logs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Simulated runs log through the production ShotLogger on simulated
    time, so real and simulated sessions go through the same analysis."""
    import csv
    import glob
    import importlib.util
    import json
    import os

    from espyresso import shot_logger

    before = shot_logger.get()
    closedloop.simulate(duration=120, start=plant.uniform(22.6), log_dir=str(tmp_path))

    (tick,) = glob.glob(os.path.join(str(tmp_path), "shot-*-tick.csv"))
    rows = list(csv.DictReader(open(tick)))
    assert float(rows[-1]["t"]) == pytest.approx(120, abs=1)  # simulated seconds, not wall time
    assert {"raw_temp", "heater", "heater_cmd", "waterTemp"} <= set(rows[0])
    meta = json.load(open(tick.replace("-tick.csv", "-meta.json")))
    assert meta["sim"]["start"]["water"] == 22.6
    assert shot_logger.get() is before  # the global logger is restored

    tools = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "review_shot.py")
    spec = importlib.util.spec_from_file_location("review_shot", tools)
    review = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(review)  # type: ignore[union-attr]
    review.summarize(tick, tick.replace("-tick.csv", "-event.csv"))
