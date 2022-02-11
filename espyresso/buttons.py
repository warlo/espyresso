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


logger = logging.getLogger(__name__)


class Buttons:
    def __init__(
        self,
        *,
        pigpio_pi: "pi",
        boiler: "Boiler",
        pump: "Pump",
        display: "Display",
        turn_off_system: Callable,
    ):
        self.pigpio_pi = pigpio_pi
        self.button_one = config.BUTTON_ONE_GPIO
        self.button_two = config.BUTTON_TWO_GPIO
        self.boiler = boiler
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
            self.button_two, pigpio.RISING_EDGE, self.callback_button_two
        )

    def rising_button_one(self, gpio, level, tick) -> None:
        logger.debug("Button one rising")
        self.button_one_timestamp = time.perf_counter()

    def falling_button_one(self, gpio, level, tick) -> None:
        time_diff = time.perf_counter() - self.button_one_timestamp
        logger.debug(f"Button one falling: {time_diff}")

        if time_diff > 5:
            return

        if time_diff > 0.25:
            self.pump.brew_shot()

    def callback_button_two(self, gpio, level, tick) -> None:
        timestamp = time.perf_counter()
        seconds = 0.0
        while seconds < 5:
            seconds = time.perf_counter() - timestamp
            self.display.notification = str(int(seconds) + 1)
            if seconds >= 2:
                self.turn_off_system()
            elif not self.pigpio_pi.read(self.button_two):
                if seconds > 0.25 and seconds < 2:
                    self.boiler.toggle_boiler()
                self.display.notification = ""
                return
            time.sleep(0.2)

    def reset_button_one(self, gpio, level, tick) -> None:
        pass
