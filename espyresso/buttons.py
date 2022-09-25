import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

import pigpio

from espyresso import config

if TYPE_CHECKING:
    from pigpio import pi

    from espyresso.boiler import Boiler
    from espyresso.pump import Pump
    from espyresso.temperature import Temperature


logger = logging.getLogger(__name__)


class Buttons:
    def __init__(
        self,
        *,
        pigpio_pi: "pi",
        boiler: "Boiler",
        temperature: "Temperature",
        pump: "Pump",
        turn_off_system: Callable[[], None],
    ):
        self.pigpio_pi = pigpio_pi
        self.button_one = config.BUTTON_ONE_GPIO
        self.button_two = config.BUTTON_TWO_GPIO
        self.boiler = boiler
        self.temperature = temperature
        self.pump = pump
        self.turn_off_system = turn_off_system

        self.button_one_timestamp: Optional[float] = None
        self.button_two_timestamp: Optional[float] = None

        self.button_one_status: Optional[str] = None
        self.button_two_status: Optional[str] = None

        self.pigpio_pi.set_mode(self.button_one, pigpio.INPUT)
        self.pigpio_pi.set_mode(self.button_two, pigpio.INPUT)
        self.pigpio_pi.set_pull_up_down(self.button_one, pigpio.PUD_DOWN)
        self.pigpio_pi.set_pull_up_down(self.button_two, pigpio.PUD_DOWN)

        self.pigpio_pi.callback(
            self.button_one, pigpio.RISING_EDGE, self.rising_button_one
        )
        self.pigpio_pi.callback(
            self.button_one, pigpio.FALLING_EDGE, self.falling_button_one
        )
        self.pigpio_pi.callback(
            self.button_two, pigpio.RISING_EDGE, self.rising_button_two
        )
        self.pigpio_pi.callback(
            self.button_two, pigpio.FALLING_EDGE, self.falling_button_two
        )

    def get_notification(self) -> Optional[str]:
        if self.button_one_timestamp and self.button_two_timestamp:
            if (
                self.button_one_timestamp > self.button_two_timestamp
                and time.perf_counter() - self.button_one_timestamp < 5
            ):
                return self.button_one_status

            if time.perf_counter() - self.button_one_timestamp < 5:
                return self.button_two_status
            return None

        if self.button_one_timestamp:
            if self.button_one_status:
                if time.perf_counter() - self.button_one_timestamp < 5:
                    return self.button_one_status
                else:
                    self.button_one_status = None
                    return None

            else:
                return str(
                    round(time.perf_counter() - self.button_one_timestamp + 1, 1)
                )

        if self.button_two_timestamp:
            if self.button_two_status:
                if time.perf_counter() - self.button_two_timestamp < 5:
                    return self.button_two_status
                else:
                    self.button_two_status = None
                    return None

            else:
                return str(
                    round(time.perf_counter() - self.button_two_timestamp + 1, 1)
                )

        return None

    def rising_button_one(self, *args: Any, **kwargs: Any) -> None:
        logger.debug("Button one rising")
        self.button_one_timestamp = time.perf_counter()

    def falling_button_one(self, *args: Any, **kwargs: Any) -> None:

        if not self.button_one_timestamp:
            return

        seconds = time.perf_counter() - self.button_one_timestamp
        self.button_one_timestamp = None
        logger.debug(f"Button one falling: {seconds}")

        if seconds < 0.25:
            return

        if seconds < 5:
            if self.temperature.get_latest_brewhead_temperature() < 80:
                _, notification = self.pump.pulse_pump()
                self.button_one_status = notification

            if self.temperature.get_latest_brewhead_temperature() > 80:
                _, notification = self.pump.brew_shot()
                self.button_one_status = notification
        else:
            self.pump.pulse_pump_steam()

    def rising_button_two(self, *args: Any, **kwargs: Any) -> None:
        self.button_two_timestamp = time.perf_counter()

    def falling_button_two(self, *args: Any, **kwargs: Any) -> None:

        if not self.button_two_timestamp:
            return

        seconds = time.perf_counter() - self.button_two_timestamp

        if seconds < 0.25:
            return

        if seconds < 2:
            self.boiler.toggle_boiler()
        else:
            self.turn_off_system()
