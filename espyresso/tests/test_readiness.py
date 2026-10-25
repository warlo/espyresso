"""Tests for ``espyresso.readiness.brew_state``: what the screen says about
whether to brew, flush or wait."""

from __future__ import annotations

import math

import pytest

from espyresso.readiness import BrewState, brew_state

WARM = dict(
    boiling=True, fault=False, steam=False, flowing=False, group_deficit=-0.5, water_from_setpoint=0.1, water_from_target=0.1
)


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, BrewState.READY),
        ({"fault": True, "boiling": False}, BrewState.FAULT),
        ({"boiling": False}, BrewState.OFF),
        ({"steam": True}, BrewState.STEAM),
        ({"flowing": True}, BrewState.FLOW),
        ({"water_from_setpoint": -3.0, "water_from_target": -3.0}, BrewState.HEATING),
        ({"water_from_setpoint": 30.0, "water_from_target": 30.0}, BrewState.COOLING),  # after steam
        ({"group_deficit": 10.0}, BrewState.FLUSH),
        ({"group_deficit": 10.0, "water_from_setpoint": -3.0}, BrewState.HEATING),  # flush once the boiler is hot
        # warm-up: the boiler is held above the setpoint, below its raised target
        ({"group_deficit": 10.0, "water_from_setpoint": 3.0, "water_from_target": -1.0}, BrewState.FLUSH),
        # warm-up easing off: the water lags its falling target a little
        ({"group_deficit": 3.0, "water_from_setpoint": 2.0, "water_from_target": 1.5}, BrewState.WARMING),
        ({"group_deficit": 3.0}, BrewState.WARMING),
        ({"group_deficit": math.inf}, BrewState.FLUSH),  # no estimate yet: assume cold
        ({"group_deficit": math.nan}, BrewState.FLUSH),
    ],
)
def test_brew_state(changes: dict, expected: BrewState) -> None:
    state = brew_state(**{**WARM, **changes}, ready_deficit=0.0, flush_deficit=6.0, water_band=1.0)

    assert state is expected


def test_thresholds_default_to_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from espyresso import config

    monkeypatch.setattr(config, "READY_GROUP_DEFICIT", 1.0)

    assert brew_state(**{**WARM, "group_deficit": 0.5}) is BrewState.READY


@pytest.mark.parametrize(
    "previous,water,expected",
    [
        (None, -0.8, BrewState.READY),
        (BrewState.HEATING, -0.8, BrewState.HEATING),  # stays until clearly back
        (BrewState.HEATING, -0.4, BrewState.READY),
    ],
)
def test_heating_has_hysteresis(previous: BrewState, water: float, expected: BrewState) -> None:
    state = brew_state(
        **{**WARM, "water_from_setpoint": water, "water_from_target": water},
        previous=previous, ready_deficit=0.0, flush_deficit=6.0, water_band=1.0,
    )

    assert state is expected


def test_cooling_has_hysteresis() -> None:
    kwargs = {**WARM, "water_from_setpoint": 1.5, "water_from_target": 1.5, "water_band": 1.0}

    assert brew_state(**kwargs, previous=None) is BrewState.READY
    assert brew_state(**kwargs, previous=BrewState.COOLING) is BrewState.COOLING
