"""Tests for ``espyresso.warmup``: the group head estimate and the boiler
target offset it asks for while the group is still cold."""

from __future__ import annotations

import math

import pytest

from espyresso import config
from espyresso.warmup import GroupWarmUp, overdrive

SP = 99.0


@pytest.mark.parametrize(
    "deficit,expected",
    [(0.0, 0.0), (-5.0, 0.0), (2.0, 0.0), (3.0, 1.0), (5.0, 3.0), (40.0, 4.0), (math.nan, 0.0)],
)
def test_overdrive_is_zero_inside_the_deadband_then_linear_and_capped(deficit: float, expected: float) -> None:
    assert overdrive(deficit, gain=1.0, deadband=2.0, max_offset=4.0) == pytest.approx(expected)


def _warmup() -> GroupWarmUp:
    return GroupWarmUp(gain=1.0, deadband=2.0, max_offset=4.0)


def _hold(
    w: GroupWarmUp, boiler: float, seconds: float, start: float = 0.0, step: float = 0.1, flow: float = 0.0
) -> float:
    t = start
    while t < start + seconds - 1e-9:
        t += step
        w.update(t, boiler=boiler, water=boiler, flow_rate=flow, setpoint=SP)
    return t


def test_group_starts_as_warm_as_the_first_reading() -> None:
    w = _warmup()

    w.update(0.0, boiler=22.6, water=22.6, flow_rate=0.0, setpoint=SP)

    assert w.group == pytest.approx(22.6)
    assert w.offset == pytest.approx(4.0)  # cold: the full offset


def test_no_offset_when_starting_with_a_warm_machine() -> None:
    w = _warmup()

    offset = w.update(0.0, boiler=SP + 0.5, water=SP, flow_rate=0.0, setpoint=SP)

    assert offset == 0.0


def test_offset_fades_to_exactly_zero_once_the_group_is_warm() -> None:
    w = _warmup()
    w.update(0.0, boiler=22.6, water=22.6, flow_rate=0.0, setpoint=SP)

    _hold(w, SP, 20 * 60)

    assert w.group == pytest.approx(w.warm_temperature(SP), abs=0.1)
    assert w.offset == 0.0


def test_estimate_is_exact_for_long_gaps() -> None:
    fine, coarse = _warmup(), _warmup()
    for w in (fine, coarse):
        w.update(0.0, boiler=22.6, water=22.6, flow_rate=0.0, setpoint=SP)

    _hold(fine, SP, 300.0, step=0.1)
    coarse.update(300.0, boiler=SP, water=SP, flow_rate=0.0, setpoint=SP)

    assert coarse.group == pytest.approx(fine.group, abs=0.05)


def test_water_flowing_through_warms_the_group_faster() -> None:
    still, flushed = _warmup(), _warmup()
    for w in (still, flushed):
        w.update(0.0, boiler=60.0, water=60.0, flow_rate=0.0, setpoint=SP)

    _hold(still, SP, 120.0)
    _hold(flushed, SP, 120.0, flow=1.5)

    assert flushed.group is not None and still.group is not None
    assert flushed.group > still.group + 3.0
    assert flushed.offset < still.offset


def test_bad_reading_leaves_the_estimate_alone() -> None:
    w = _warmup()
    w.update(0.0, boiler=50.0, water=50.0, flow_rate=0.0, setpoint=SP)

    w.update(0.1, boiler=math.nan, water=50.0, flow_rate=0.0, setpoint=SP)

    assert w.group == pytest.approx(50.0, abs=0.1)


def test_defaults_come_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "WARMUP_MAX_OFFSET", 0.0)

    w = GroupWarmUp()

    assert w.update(0.0, boiler=22.6, water=22.6, flow_rate=0.0, setpoint=SP) == 0.0
