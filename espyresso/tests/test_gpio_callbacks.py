"""Every pigpio callback must swallow its own exceptions.

pigpio delivers all GPIO callbacks (temperature sensor, flow meter,
buttons, ranger) on one notification thread with no exception handling.
One raising callback ends that thread for good: the temperature sensor
stops, control stops, and the hardware PWM keeps the element at its last
duty. These tests invoke the callbacks exactly as pigpio would, through
the functions handed to ``pigpio_pi.callback``.
"""

from __future__ import annotations

import time
from typing import Any, Callable, List
from unittest.mock import Mock

import pytest

from espyresso import config
from espyresso.buttons import Buttons
from espyresso.flow import Flow
from espyresso.ranger import Ranger
from espyresso.utils import safe_callback


def _registered(pi: Mock) -> List[Callable[..., Any]]:
    return [c.args[2] for c in pi.callback.call_args_list]


def test_safe_callback_logs_and_swallows_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    def boom(gpio: int, level: int, tick: int) -> None:
        raise RuntimeError("boom")

    safe_callback(boom)(21, 0, 123)

    assert "boom" in caplog.text


def test_safe_callback_passes_arguments_through() -> None:
    seen = []
    safe_callback(lambda *a: seen.append(a))(5, 1, 42)
    assert seen == [(5, 1, 42)]


def test_button_callbacks_never_raise_into_pigpio() -> None:
    pi = Mock()
    pump = Mock()
    pump.brew_shot.side_effect = NameError("shot_seconds")
    temperature = Mock()
    temperature.get_latest_brewhead_temperature.return_value = 90.0
    buttons = Buttons(pigpio_pi=pi, boiler=Mock(), temperature=temperature, pump=pump, turn_off_system=Mock())
    buttons.button_one_timestamp = time.perf_counter() - 1.0  # a 1 s press: brew
    (falling,) = [cb for cb in _registered(pi) if cb.__name__ == "falling_button_one"]

    falling(config.BUTTON_ONE_GPIO, 0, 0)

    pump.brew_shot.assert_called_once()


def test_flow_callback_never_raises_into_pigpio() -> None:
    pi = Mock()
    queue = Mock()
    queue.add_to_queue.side_effect = RuntimeError("display queue broke")
    Flow(pigpio_pi=pi, flow_queue=queue)
    (cb,) = _registered(pi)

    for i in range(5):  # enough pulses to compute a flow rate and enqueue it
        cb(5, 1, i)
        time.sleep(0.03)


def test_ranger_callbacks_never_raise_into_pigpio() -> None:
    pi = Mock()
    ranger = Ranger(pigpio_pi=pi)
    ranger.done = Mock()
    ranger.done.set.side_effect = RuntimeError("event broke")

    for cb in _registered(pi):
        cb(27, 0, 0)
