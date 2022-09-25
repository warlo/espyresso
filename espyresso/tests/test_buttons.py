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
