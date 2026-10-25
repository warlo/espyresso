"""Tests for ``espyresso.pcontroller.PController``.

The MPC is rich and physics-y; we don't try to validate the numerics
end-to-end. Instead we pin down the *contract* of ``update``:

  * not boiling → heater power is exactly 0
  * the returned tuple has 7 thermal-mass values in a known order
  * the last value of the tuple is the raw measured temperature
  * heater power is always in the normalized [0, 1] range
  * with no flow and at setpoint, the heater settles to a small positive value

These are the invariants we'll lean on when converting hot-path
``logger.debug(f"...")`` calls to lazy formatting — the controller's
outputs must not change.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from espyresso import config
from espyresso.pcontroller import PController


@pytest.fixture
def flow_zero() -> Mock:
    flow = Mock()
    flow.get_flow_rate.return_value = 0.0
    return flow


def test_not_boiling_returns_zero_heater_power(flow_zero: Mock) -> None:
    p = PController(initial_temperature=22.0, flow=flow_zero)
    heater, masses = p.update(temperature=22.0, boiling=False)
    assert heater == 0


def test_returned_tuple_shape(flow_zero: Mock) -> None:
    p = PController(initial_temperature=22.0, flow=flow_zero)
    _, masses = p.update(temperature=22.0, boiling=False)
    assert len(masses) == 7
    # All entries are floats
    for v in masses:
        assert isinstance(v, float)


def test_returned_tuple_last_entry_is_measured_temperature(flow_zero: Mock) -> None:
    p = PController(initial_temperature=22.0, flow=flow_zero)
    _, masses = p.update(temperature=42.42, boiling=False)
    assert masses[-1] == 42.42


def test_heater_power_normalized_to_unit_interval(flow_zero: Mock) -> None:
    """When boiling, heater power must be in [0, 1] regardless of state."""
    p = PController(initial_temperature=22.0, flow=flow_zero)
    # cold start, target high — controller wants max power
    heater, _ = p.update(temperature=22.0, boiling=True)
    assert 0.0 <= heater <= 1.0


def test_heater_power_zero_when_already_at_setpoint(flow_zero: Mock) -> None:
    """At setpoint with no flow, heater power should be very small."""
    p = PController(initial_temperature=config.TARGET_TEMP, flow=flow_zero)
    # Drive several updates to let thermal masses equilibrate around setpoint
    for _ in range(10):
        heater, _ = p.update(temperature=config.TARGET_TEMP, boiling=True)
    # Some heater output is expected (we lose heat to ambient) but it
    # must stay well below full power.
    assert 0.0 <= heater < 0.5


def test_set_target_temp_changes_setpoint(flow_zero: Mock) -> None:
    p = PController(initial_temperature=22.0, flow=flow_zero)
    assert p.temp_setpoint == config.TARGET_TEMP
    p.set_target_temp(135.0)
    assert p.temp_setpoint == 135.0


def test_cold_start_drives_full_power(flow_zero: Mock) -> None:
    """22°C and boiling with a 95°C setpoint → heater pinned at 1.0."""
    p = PController(initial_temperature=22.0, flow=flow_zero)
    heater, _ = p.update(temperature=22.0, boiling=True)
    assert heater == pytest.approx(1.0)


# ------------------------------------------------------------------ #
#  Self-healing behaviour (fake clock: PController reads time.perf_counter)
# ------------------------------------------------------------------ #

import math  # noqa: E402
import types  # noqa: E402

from espyresso import pcontroller as pcm  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(pcm, "time", types.SimpleNamespace(perf_counter=lambda: c.now))
    return c


def _run(p: PController, clock: Clock, temperature: float, seconds: float, boiling: bool = True) -> float:
    heater = 0.0
    for _ in range(int(round(seconds / 0.1))):
        clock.advance(0.1)
        heater, _ = p.update(temperature=temperature, boiling=boiling)
    return heater


def test_long_gap_resyncs_model_to_sensor_instead_of_integrating(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=93.0, flow=flow_zero)
    _run(p, clock, 93.0, 5)

    clock.advance(30.0)  # controller stalled (e.g. callbacks paused) for 30 s
    p.update(temperature=93.0, boiling=True)

    # Integrating a 30 s Euler step drove the element to about -59 °C.
    assert p.elementTemp == pytest.approx(93.0, abs=1.0)
    assert p.waterTemp == pytest.approx(93.0, abs=1.0)
    assert p.modeledSensorTemp == pytest.approx(93.0, abs=0.5)


def test_first_update_after_slow_startup_does_not_overcorrect(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=60.0, flow=flow_zero)
    clock.advance(6.0)  # every boot has a 4.5-7 s first step (app construction)

    # The boiler warmed during construction; the correction gain is
    # dt * MPC_SMOOTHING, which is 3x the error after a 6 s step.
    p.update(temperature=66.0, boiling=True)

    assert p.modeledSensorTemp == pytest.approx(66.0, abs=0.5)


def test_persistent_large_model_error_resyncs_model(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=95.0, flow=flow_zero)
    p.set_target_temp(95.0)
    _run(p, clock, 95.0, 10)

    # Boiler is really much hotter than the model thinks (e.g. heated while
    # the app was down). A 15 K error never happens in normal operation.
    _run(p, clock, 110.0, 1.5)

    assert p.waterTemp == pytest.approx(110.0, abs=1.0)


def test_single_noisy_tick_does_not_resync(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=95.0, flow=flow_zero)
    p.set_target_temp(95.0)
    _run(p, clock, 95.0, 10)

    _run(p, clock, 110.0, 0.1)

    assert p.waterTemp == pytest.approx(95.0, abs=1.0)


@pytest.mark.parametrize("setpoint", [92.0, 98.0, 135.0])
def test_full_model_correction_works_at_any_setpoint(clock: Clock, flow_zero: Mock, setpoint: float) -> None:
    p = PController(initial_temperature=setpoint, flow=flow_zero)
    p.set_target_temp(setpoint)

    _run(p, clock, setpoint, 30)

    assert p.diagnostics["steadystate"] is True


@pytest.mark.parametrize(
    "temperature,expected_seconds",
    [
        (22.0, 6.0),   # cold: capped
        (90.0, 2.22),  # 5 K * 1200 J/K * 0.5 / 1350 W
        (95.0, 0.0),   # at setpoint
        (101.0, 0.0),  # above setpoint
    ],
)
def test_boot_boost_is_sized_from_the_first_reading(temperature: float, expected_seconds: float) -> None:
    assert pcm.boot_boost_seconds(temperature, setpoint=95.0) == pytest.approx(expected_seconds, abs=0.01)


def test_boost_runs_full_power_for_its_duration_then_hands_back(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=95.0, flow=flow_zero)
    p.set_target_temp(95.0)
    _run(p, clock, 95.0, 5)

    p.start_boost(2.0)
    during = _run(p, clock, 95.0, 1.9)
    after = _run(p, clock, 95.0, 0.5)

    assert during == 1.0
    assert after < 1.0


def test_boost_energy_is_known_to_the_model(clock: Clock, flow_zero: Mock) -> None:
    boosted = PController(initial_temperature=95.0, flow=flow_zero)
    plain = PController(initial_temperature=95.0, flow=flow_zero)
    for p in (boosted, plain):
        p.set_target_temp(95.0)  # at setpoint: without boost it barely heats
        clock.now = 1000.0
        p.lastBoilerPidTime = clock.now
    boosted.start_boost(3.0)

    clock.now = 1000.0
    _run(boosted, clock, 95.0, 3)
    clock.now = 1000.0
    _run(plain, clock, 95.0, 3)

    # 3 s at 1350 W heats the modelled element noticeably more.
    assert boosted.elementTemp > plain.elementTemp + 3.0


def test_boost_does_nothing_when_not_boiling(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=60.0, flow=flow_zero)
    p.start_boost(5.0)

    assert _run(p, clock, 60.0, 1, boiling=False) == 0


def _shot_controller(clock: Clock) -> PController:
    flow = Mock()
    flow.get_flow_rate.return_value = 1.0
    p = PController(initial_temperature=95.0, flow=flow)
    p.set_target_temp(95.0)
    _run(p, clock, 95.0, 5)
    return p


def test_flow_horizon_adds_heat_during_a_known_shot(clock: Clock) -> None:
    with_horizon, without = _shot_controller(clock), _shot_controller(clock)

    heat = []
    for p, horizon in ((with_horizon, 20.0), (without, 0.0)):
        p.set_flow_horizon(horizon)
        clock.advance(0.1)
        heat.append(p.update(temperature=93.0, boiling=True)[0])

    assert heat[0] > heat[1]


def test_flow_horizon_expires_if_not_refreshed(clock: Clock) -> None:
    stale, without = _shot_controller(clock), _shot_controller(clock)
    stale.set_flow_horizon(20.0)
    clock.advance(2.0)  # pump thread died: nobody refreshes the horizon

    heat = []
    for p in (stale, without):
        clock.advance(0.1)
        heat.append(p.update(temperature=93.0, boiling=True)[0])

    assert heat[0] == pytest.approx(heat[1])


def test_nan_temperature_turns_heater_off_without_poisoning_model(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=90.0, flow=flow_zero)
    _run(p, clock, 90.0, 2)

    clock.advance(0.1)
    heater, _ = p.update(temperature=float("nan"), boiling=True)
    after = _run(p, clock, 90.0, 1)

    assert heater == 0
    assert math.isfinite(after)
    assert math.isfinite(p.waterTemp)


def test_model_stops_heating_when_boiler_is_turned_off(clock: Clock, flow_zero: Mock) -> None:
    p = PController(initial_temperature=40.0, flow=flow_zero)
    _run(p, clock, 40.0, 1)  # cold: full power
    element_at_switch_off = p.elementTemp

    _run(p, clock, 40.0, 5, boiling=False)

    # The real element is off, so the modelled one must not keep heating.
    assert p.elementTemp < element_at_switch_off + 1.0


def test_target_offset_raises_what_the_controller_regulates_to(clock: Clock, flow_zero: Mock) -> None:
    held, raised = (PController(initial_temperature=config.TARGET_TEMP, flow=flow_zero) for _ in range(2))
    raised.set_target_offset(4.0)

    held_heater = _run(held, clock, config.TARGET_TEMP, 5)
    raised_heater = _run(raised, clock, config.TARGET_TEMP, 5)

    assert raised.temp_setpoint == config.TARGET_TEMP  # the base setpoint is unchanged
    assert raised.target == pytest.approx(config.TARGET_TEMP + 4.0)
    assert raised_heater > held_heater + 0.1  # heats towards the raised target
    assert raised.diagnostics["target_offset"] == 4.0
    assert held.diagnostics["target_offset"] == 0.0


def test_non_finite_target_offset_is_ignored(flow_zero: Mock) -> None:
    p = PController(initial_temperature=22.0, flow=flow_zero)

    p.set_target_offset(math.nan)

    assert p.target == config.TARGET_TEMP
