import time
from unittest.mock import Mock

import pytest

from espyresso.buttons import Buttons


@pytest.fixture
def buttons() -> Buttons:

    boiler = Mock()
    temperature = Mock()
    pump = Mock()

    def a() -> None:
        pass

    buttons = Buttons(
        pigpio_pi=Mock(),
        boiler=boiler,
        temperature=temperature,
        pump=pump,
        turn_off_system=a,
    )
    return buttons


@pytest.mark.parametrize(
    "timestamp_attr,status_attr,status",
    [
        ("button_one_timestamp", "button_one_status", "Not boiling"),
        ("button_two_timestamp", "button_two_status", "Not boiling"),
    ],
)
def test_buttons_notification_status(
    timestamp_attr: str, status_attr: str, status: str, buttons: Buttons
) -> None:

    t = time.perf_counter()
    setattr(buttons, timestamp_attr, t)
    setattr(buttons, status_attr, status)

    assert buttons.get_notification() == status


@pytest.mark.parametrize(
    "timestamp_attr,status_attr,status",
    [
        ("button_one_timestamp", "button_one_status", "Not boiling"),
        ("button_two_timestamp", "button_two_status", "Not boiling"),
    ],
)
def test_buttons_notification_status_over_5sec(
    timestamp_attr: str, status_attr: str, status: str, buttons: Buttons
) -> None:

    t = time.perf_counter() - 6
    setattr(buttons, timestamp_attr, t)
    setattr(buttons, status_attr, status)

    assert buttons.get_notification() is None


@pytest.mark.parametrize(
    "timestamp_attr",
    [
        ("button_one_timestamp"),
        ("button_two_timestamp"),
    ],
)
def test_buttons_notification_timer(timestamp_attr: str, buttons: Buttons) -> None:

    t = time.perf_counter()
    setattr(buttons, timestamp_attr, t)

    assert buttons.get_notification() == "1.0"


@pytest.mark.parametrize(
    "timestamp_attr",
    [
        ("button_one_timestamp"),
        ("button_two_timestamp"),
    ],
)
def test_buttons_notification_timer_over_5sec(
    timestamp_attr: str, buttons: Buttons
) -> None:

    t = time.perf_counter() - 6
    setattr(buttons, timestamp_attr, t)

    assert buttons.get_notification() == "7.0"


@pytest.mark.parametrize("ready,routine", [(False, "pulse_pump"), (True, "brew_shot")])
def test_short_press_preheats_until_brew_head_is_ready(ready: bool, routine: str) -> None:
    pump = Mock()
    pump.pulse_pump.return_value = (True, None)
    pump.brew_shot.return_value = (True, None)
    temperature = Mock()
    temperature.brewhead_ready.return_value = ready
    buttons = Buttons(pigpio_pi=Mock(), boiler=Mock(), temperature=temperature, pump=pump, turn_off_system=Mock())
    buttons.button_one_timestamp = time.perf_counter() - 1.0

    buttons.falling_button_one()

    called = [name for name in ("pulse_pump", "brew_shot") if getattr(pump, name).called]
    assert called == [routine]
