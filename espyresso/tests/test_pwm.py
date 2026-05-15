"""Tests for ``espyresso.pwm.PWM``.

Thin wrapper around pigpio; the value-to-duty-cycle math and the
display-value formatting are the bits worth pinning down.
"""

from __future__ import annotations

from unittest.mock import Mock

from espyresso.pwm import PWM


def test_pwm_set_value_calls_hardware_pwm_with_duty_cycle() -> None:
    pi = Mock()
    pwm = PWM(pi, pwm_gpio=12, freq=2)
    pwm.set_value(0.5)
    pi.hardware_PWM.assert_called_once_with(12, 2, 500_000)


def test_pwm_set_value_zero() -> None:
    pi = Mock()
    pwm = PWM(pi, pwm_gpio=12, freq=2)
    pwm.set_value(0.0)
    pi.hardware_PWM.assert_called_once_with(12, 2, 0)


def test_pwm_set_value_full() -> None:
    pi = Mock()
    pwm = PWM(pi, pwm_gpio=12, freq=2)
    pwm.set_value(1.0)
    pi.hardware_PWM.assert_called_once_with(12, 2, 1_000_000)


def test_pwm_display_value_formats_percent() -> None:
    pwm = PWM(Mock(), pwm_gpio=12, freq=2)
    pwm.value = 0.456
    assert pwm.get_display_value() == "45.6"
    pwm.value = 0.0
    assert pwm.get_display_value() == "0.0"
    pwm.value = 1.0
    assert pwm.get_display_value() == "100.0"
