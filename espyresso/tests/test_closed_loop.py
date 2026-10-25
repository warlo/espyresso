"""Closed-loop regression tests: the production control path (Temperature,
PController, SafetyGuard, Boiler, Watchdog) against the plant fitted to this
machine's logs (espyresso/sim). Each test pins a behaviour that was wrong
before, so tuning can't silently bring it back.

The plant is only as good as the logs it was fitted to (four cold starts;
leave-one-out 1.1-2.9 C). Boiler-side behaviour is the trustworthy
part; puck temperatures depend on unmeasured group coupling, so they are
compared relative to each other, not asserted as absolute truths.
"""

from __future__ import annotations

import pytest

from espyresso import config
from espyresso.sim import closedloop, plant, scenarios

SP = config.TARGET_TEMP


@pytest.fixture
def no_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the controller's own behaviour; the warm-up (a deliberate hotter
    boiler while the group is cold) is tested on its own below."""
    monkeypatch.setattr(config, "WARMUP_MAX_OFFSET", 0.0)


@pytest.mark.usefixtures("no_warmup")
def test_cold_start_reaches_setpoint_without_large_overshoot() -> None:
    run = closedloop.simulate(duration=360, start=plant.uniform(22.6))

    assert run.first_time(lambda r: abs(r["water"] - SP) < 1.0) < 240
    assert run.max("water") < SP + 2.0


def test_restart_at_setpoint_does_not_overshoot() -> None:
    # The old blind 6 s boot boost pushed the water to setpoint + 4.3 C here.
    run = closedloop.simulate(duration=240, start=plant.at_setpoint(SP))

    assert run.max("water") < SP + 1.0


@pytest.mark.usefixtures("no_warmup")
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


@pytest.mark.usefixtures("no_warmup")
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


def test_controller_blind_to_flow_lets_the_boiler_drop_further() -> None:
    """Comparing with published measurements from plain-PID machines needs a
    controller that can't see the flow meter (no feed-forward)."""
    flow = scenarios.manual_shots([600.0])
    seeing = closedloop.simulate(duration=700, start=plant.uniform(22.6), flow=flow)
    blind = closedloop.simulate(duration=700, start=plant.uniform(22.6), flow=scenarios.manual_shots([600.0]), controller_sees_flow=False)

    assert blind.max("water", after=600) > 0  # ran
    assert min(r["water"] for r in blind.window(600, 640)) < min(r["water"] for r in seeing.window(600, 640)) - 0.5


def _published_pid_shot_puck_drop(**params: float) -> float:
    """A 2005 thermocouple study of a PID Gaggia Classic (setpoint 99.5, 60 mL
    in 30 s after a 20 min warm-up, controller blind to flow) measured the
    water above the puck falling 7.5-10 C over the shot."""
    start = 1200.0

    def flow(t: float, temperature: float):  # type: ignore[no-untyped-def]
        return (2.0 if start <= t < start + 30 else 0.0), None

    run = closedloop.simulate(
        duration=start + 40,
        start=plant.uniform(22.6),
        params=plant.fitted(**params),
        flow=flow,
        setpoint=99.5,
        controller_sees_flow=False,
        auto_off=False,
    )
    first = [r["puck"] for r in run.window(start, start + 3) if r["flow"] > 0]
    last = [r["puck"] for r in run.window(start + 27, start + 30) if r["flow"] > 0]
    return sum(first) / len(first) - sum(last) / len(last)


def test_plant_reproduces_published_puck_drop_of_a_pid_classic() -> None:
    """Pins eps (how much heat the brew head takes from the water), which the
    boiler sensor can't see. The controller's own assumption (1.0) gives a
    fraction of the measured drop."""
    assert 7.5 < _published_pid_shot_puck_drop() < 10.0
    assert _published_pid_shot_puck_drop(eps=1.0) < 4.0



# ------------------------------------------------------------------ #
#  Warm-up (espyresso/warmup.py): hotter boiler while the group is cold.
#  Checked on every plant that fits the logs (plant.candidates()), since
#  they disagree on exactly what the warm-up depends on.
# ------------------------------------------------------------------ #


def _shot_puck(params: dict, at: float, preheat: bool = False) -> float:
    flow = scenarios.preheat_then_shot(90.0, at) if preheat else scenarios.pi_shots([at])
    run = closedloop.simulate(duration=at + 60, start=plant.uniform(22.6), params=params, flow=flow, auto_off=False)
    pucks = [r["puck"] for r in run.window(at, at + scenarios.SHOT_SECONDS) if r["flow"] > 0]
    return sum(pucks) / len(pucks)


def _warm_machine_puck(params: dict) -> float:
    return _shot_puck(params, 2400.0)


def test_warm_up_brings_an_early_shot_close_to_a_warm_one(monkeypatch: pytest.MonkeyPatch) -> None:
    params = plant.fitted()
    warm = _warm_machine_puck(params)

    with_warm_up = _shot_puck(params, 300.0) - warm
    monkeypatch.setattr(config, "WARMUP_MAX_OFFSET", 0.0)
    without = _shot_puck(params, 300.0) - warm

    assert abs(with_warm_up) < abs(without) - 1.0


@pytest.mark.parametrize("name", sorted(plant.candidates()))
def test_warm_up_never_makes_early_shots_much_too_hot(name: str) -> None:
    params = plant.candidates()[name]
    warm = _warm_machine_puck(params)

    for minutes in (4, 5, 6, 7):
        assert _shot_puck(params, minutes * 60.0) - warm < 1.2, minutes
    for minutes in (4, 6):  # after a preheat flush at 1.5 min
        assert _shot_puck(params, minutes * 60.0, preheat=True) - warm < 1.2, minutes


def test_warm_up_hands_back_an_untouched_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    run = closedloop.simulate(duration=1500, start=plant.uniform(22.6), auto_off=False)
    monkeypatch.setattr(config, "WARMUP_MAX_OFFSET", 0.0)
    plain = closedloop.simulate(duration=1500, start=plant.uniform(22.6), auto_off=False)

    assert run.max("target", after=600) == SP  # exactly off once the group is warm

    def idle(r: closedloop.Run) -> float:
        rows = r.window(900, 1500)
        return sum(x["water"] for x in rows) / len(rows)

    assert idle(run) == pytest.approx(idle(plain), abs=0.05)


@pytest.mark.parametrize("name", sorted(plant.candidates()) + ["1240 W element"])
def test_warm_up_keeps_the_display_clear_of_the_safety_limit(name: str) -> None:
    params = plant.fitted(P_max=1240.0) if name == "1240 W element" else plant.candidates()[name]
    run = closedloop.simulate(duration=600, start=plant.uniform(22.6), params=params, auto_off=False)

    assert run.max("sensor") < SP + config.SAFETY_MAX_ABOVE_SETPOINT - 3.0
