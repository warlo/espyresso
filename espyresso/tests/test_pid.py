"""Tests for the (currently unused) ``espyresso.pid.PID`` controller.

These tests pin down the existing behavior so we have a safety net if
the PID is reintroduced or modified.
"""

from __future__ import annotations

import pytest

from espyresso.pid import PID


def test_pid_defaults() -> None:
    pid = PID()
    assert pid.p_gain == 1.0
    assert pid.i_gain == 0.0
    assert pid.d_gain == 0.0
    assert pid.i_min == -1.0
    assert pid.i_max == 1.0
    assert pid.i_state == 0.0
    assert pid.d_state == 0.0


def test_pid_pure_proportional() -> None:
    pid = PID()
    # default p=1.0, i=0, d=0  → output = error
    assert pid.update(error=5.0, position=0.0) == 5.0
    assert pid.update(error=-2.0, position=0.0) == -2.0


def test_pid_integrator_accumulates_and_clamps_high() -> None:
    pid = PID()
    pid.set_pid_gains(p_gain=0.0, i_gain=1.0, d_gain=0.0)
    pid.set_integrator_limits(i_min=-10.0, i_max=2.0)
    pid.update(error=5.0, position=0.0)
    # i_state clamped to 2.0
    assert pid.i_state == 2.0
    out = pid.update(error=5.0, position=0.0)
    assert pid.i_state == 2.0  # still clamped
    assert out == pytest.approx(2.0)


def test_pid_integrator_accumulates_and_clamps_low() -> None:
    pid = PID()
    pid.set_pid_gains(p_gain=0.0, i_gain=1.0, d_gain=0.0)
    pid.set_integrator_limits(i_min=-3.0, i_max=10.0)
    pid.update(error=-5.0, position=0.0)
    assert pid.i_state == -3.0


def test_pid_derivative_reacts_to_position_change() -> None:
    pid = PID()
    pid.set_pid_gains(p_gain=0.0, i_gain=0.0, d_gain=2.0)
    # First call: d_state was 0, position is 10 → d_term = 2 * (0 - 10) = -20
    assert pid.update(error=0.0, position=10.0) == pytest.approx(-20.0)
    # Second call: d_state is now 10, position is 15 → d_term = 2 * (10 - 15) = -10
    assert pid.update(error=0.0, position=15.0) == pytest.approx(-10.0)
