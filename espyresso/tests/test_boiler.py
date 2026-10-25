"""Tests for ``espyresso.boiler.Boiler``.

Boiler talks to pigpio via PWM; we mock both. The interesting behavior
is the *safety* logic — set_value should be a no-op when not boiling or
when an override is active, and bounds-clamp values to [0, 1].
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from espyresso.boiler import Boiler


@pytest.fixture
def queue_recorder() -> Mock:
    return Mock()


@pytest.fixture
def reset_recorder() -> Mock:
    return Mock()


@pytest.fixture
def boiler(queue_recorder: Mock, reset_recorder: Mock) -> Boiler:
    return Boiler(
        pigpio_pi=Mock(),
        reset_started_time=reset_recorder,
        add_to_queue=queue_recorder,
        boiling=False,
    )


def test_boiler_initial_state(boiler: Boiler) -> None:
    assert boiler.get_boiling() is False
    assert boiler.pwm_override is None


def test_turn_on_boiler_sets_flag_and_resets_time(
    boiler: Boiler, reset_recorder: Mock
) -> None:
    boiler.turn_on_boiler()
    assert boiler.get_boiling() is True
    reset_recorder.assert_called_once()


def test_turn_off_boiler(boiler: Boiler) -> None:
    boiler.turn_on_boiler()
    boiler.turn_off_boiler()
    assert boiler.get_boiling() is False
    assert boiler.pwm_override is None


def test_toggle_boiler_flips_state(boiler: Boiler, reset_recorder: Mock) -> None:
    assert boiler.get_boiling() is False
    boiler.toggle_boiler()
    assert boiler.get_boiling() is True
    reset_recorder.assert_called_once()
    boiler.toggle_boiler()
    assert boiler.get_boiling() is False


def test_set_value_noop_when_not_boiling(
    boiler: Boiler, queue_recorder: Mock
) -> None:
    boiler.set_value(0.5)
    queue_recorder.assert_not_called()


def test_set_value_noop_when_override_active(
    boiler: Boiler, queue_recorder: Mock
) -> None:
    boiler.turn_on_boiler()
    queue_recorder.reset_mock()
    boiler.set_pwm_override(0.3)
    queue_recorder.reset_mock()
    boiler.set_value(0.7)
    queue_recorder.assert_not_called()


def test_set_value_clamps_above_one(boiler: Boiler, queue_recorder: Mock) -> None:
    boiler.turn_on_boiler()
    boiler.set_value(2.5)
    # add_to_queue called with the clamped value (rounded * 100)
    queue_recorder.assert_called_once_with((100.0,))


def test_set_value_clamps_below_zero(boiler: Boiler, queue_recorder: Mock) -> None:
    boiler.turn_on_boiler()
    boiler.set_value(-1.0)
    queue_recorder.assert_called_once_with((0.0,))


def test_set_value_normal_range(boiler: Boiler, queue_recorder: Mock) -> None:
    boiler.turn_on_boiler()
    boiler.set_value(0.456)
    queue_recorder.assert_called_once_with((45.6,))


# ------------------------------------------------------------------ #
#  Safety: what actually reaches the PWM hardware (pigpio boundary)
# ------------------------------------------------------------------ #


def _duties(pi: Mock) -> list:
    """Duty cycles written to the boiler's hardware PWM, in order."""
    from espyresso import config

    return [c.args[2] for c in pi.hardware_PWM.call_args_list if c.args[0] == config.BOILER_PWM_GPIO]


def test_boiling_at_boot_does_not_drive_the_element_blind(monkeypatch: pytest.MonkeyPatch) -> None:
    from espyresso import config

    monkeypatch.setattr(config, "DEBUG", False)  # behave as on the Pi
    pi = Mock()
    Boiler(pigpio_pi=pi, reset_started_time=Mock(), add_to_queue=Mock(), boiling=True)
    # Heating waits for the controller's first measurement.
    assert all(duty == 0 for duty in _duties(pi))


def test_force_off_zeroes_pwm_even_when_not_boiling() -> None:
    pi = Mock()
    boiler = Boiler(pigpio_pi=pi, reset_started_time=Mock(), add_to_queue=Mock(), boiling=True)
    boiler.set_value(0.6)
    boiler.boiling = False  # e.g. turned off, but a stale duty is still on the pin

    boiler.force_off()

    assert _duties(pi)[-1] == 0


def test_force_off_overrides_an_active_pwm_override() -> None:
    pi = Mock()
    boiler = Boiler(pigpio_pi=pi, reset_started_time=Mock(), add_to_queue=Mock(), boiling=True)
    boiler.set_pwm_override(0.3)

    boiler.force_off()

    assert _duties(pi)[-1] == 0


def test_set_value_treats_nan_as_off() -> None:
    pi = Mock()
    boiler = Boiler(pigpio_pi=pi, reset_started_time=Mock(), add_to_queue=Mock(), boiling=True)
    boiler.set_value(0.5)

    boiler.set_value(float("nan"))

    assert _duties(pi)[-1] == 0


def test_switching_on_again_clears_a_fault(boiler: Boiler) -> None:
    boiler.fault = "sensor not responding"

    boiler.toggle_boiler()

    assert boiler.get_boiling() is True
    assert boiler.fault is None
