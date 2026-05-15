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
