"""Tests for espyresso.flow_calibration: turning timed meter pulses and scale
readings into the flow meter's millilitres per pulse."""

from __future__ import annotations

import pytest

from espyresso import flow_calibration as fc


def test_slope_of_a_straight_line() -> None:
    assert fc.slope([(0.0, 1.0), (1.0, 3.0), (2.0, 5.0)]) == pytest.approx(2.0)


def test_grams_per_pulse_ignores_a_constant_scale_delay() -> None:
    """The scale reports over Bluetooth a few hundred ms late; comparing
    rates (slopes), not totals, makes that delay irrelevant."""
    pulses = [(t / 10, t / 10 * 8.0) for t in range(0, 101)]  # 8 pulses/s
    grams = [(t / 10 + 0.4, t / 10 * 3.8) for t in range(0, 101)]  # 3.8 g/s, 0.4 s late

    step = fc.measure_step(pulses, grams, start=2.0, end=9.0)

    assert step.pulse_rate == pytest.approx(8.0)
    assert step.grams_per_pulse == pytest.approx(3.8 / 8.0)


def test_table_converts_grams_to_millilitres_of_cold_inlet_water() -> None:
    """The meter sits on the cold side: a gram there is 1/0.998 mL."""
    steps = [fc.Step(pulse_rate=10.0, grams_per_pulse=0.4790), fc.Step(pulse_rate=2.0, grams_per_pulse=0.4990)]

    rates, ml = fc.table(steps)

    assert rates == (2.0, 10.0)  # sorted by rate
    assert ml == pytest.approx((0.5, 0.4800), abs=1e-4)


def test_steps_are_found_where_the_pump_ran() -> None:
    marks = [("on", 1.0), ("off", 11.0), ("on", 13.0), ("off", 23.0)]

    windows = fc.step_windows(marks, settle=3.0, trim=1.0)

    assert windows == [(4.0, 10.0), (16.0, 22.0)]
