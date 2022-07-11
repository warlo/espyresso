import logging
import time
from typing import TYPE_CHECKING, Callable

import pigpio

from espyresso import config

if TYPE_CHECKING:
    from pigpio import pi

    from espyresso.boiler import Boiler
    from espyresso.display import Display
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
        display: "Display",
        turn_off_system: Callable,
    ):
        self.pigpio_pi = pigpio_pi
        self.button_one = config.BUTTON_ONE_GPIO
        self.button_two = config.BUTTON_TWO_GPIO
        self.boiler = boiler
        self.temperature = temperature
        self.pump = pump
        self.display = display
        self.turn_off_system = turn_off_system

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

    def rising_button_one(self, gpio, level, tick) -> None:
        logger.debug("Button one rising")
        self.button_one_timestamp = time.perf_counter()

    def falling_button_one(self, gpio, level, tick) -> None:
        seconds = time.perf_counter() - self.button_one_timestamp
        logger.debug(f"Button one falling: {seconds}")

        if seconds < 0.25 or seconds > 5:
            return

        if self.temperature.get_latest_brewhead_temperature() < 80:
            _, notification = self.pump.pulse_pump()
            self.display.set_notification(notification or "")

        if self.temperature.get_latest_brewhead_temperature() > 80:
            _, notification = self.pump.brew_shot()
            self.display.set_notification(notification or "")

    def rising_button_two(self, *args, **kwargs) -> None:
        self.button_two_timestamp = time.perf_counter()
        self.display.start_notification_timer()

    def falling_button_two(self, *args, **kwargs) -> None:

        self.display.stop_notification_timer()
        seconds = time.perf_counter() - self.button_two_timestamp

        if seconds < 0.25 or seconds > 5:
            return

        if seconds < 2:
            self.boiler.toggle_boiler()
            self.display.set_notification("")
        else:
            self.turn_off_system()
