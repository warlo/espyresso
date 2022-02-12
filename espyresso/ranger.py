#!/usr/bin/env python3
import collections
import logging
import statistics
import threading
import time
from typing import TYPE_CHECKING, Deque

import pigpio

from espyresso import config
from espyresso.utils import linear_transform

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pigpio import pi


class Ranger(threading.Thread):
    def __init__(
        self,
        *args,
        pigpio_pi: "pi",
        **kwargs,
    ):
        self.pigpio_pi = pigpio_pi
        self.ranger_echo_in_gpio = config.RANGER_ECHO_IN
        self.ranger_trigger_out_gpio = config.RANGER_TRIGGER_OUT

        self.pigpio_pi.set_mode(self.ranger_echo_in_gpio, pigpio.INPUT)
        self.pigpio_pi.set_mode(self.ranger_trigger_out_gpio, pigpio.OUTPUT)

        self.pigpio_pi.callback(self.ranger_echo_in_gpio, pigpio.RISING_EDGE, self.rise)
        self.pigpio_pi.callback(
            self.ranger_echo_in_gpio, pigpio.FALLING_EDGE, self.fall
        )
        self.done = threading.Event()

        self.history: Deque[float] = collections.deque(maxlen=10)
        self.high = 0
        self.low = 0

        self._stop_event = threading.Event()
        super().__init__(*args, **kwargs)

    def rise(self, gpio, level, tick) -> None:
        self.high = tick

    def fall(self, gpio, level, tick) -> None:
        self.low = tick - self.high
        self.done.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.done.clear()
            self.pigpio_pi.gpio_trigger(self.ranger_trigger_out_gpio, 50, 1)
            if self.done.wait(timeout=5):
                distance = linear_transform(self.low, 180, 860, 100, 0)
                self.history.append(distance)

                logger.debug(
                    f"Ranger distance: {distance}; low: {self.low}; high: {self.high}"
                )
            time.sleep(0.5)

    def stop(self) -> None:
        logger.debug("Ranger stopping")
        self._stop_event.set()

    def get_current_distance(self) -> float:
        return statistics.median(self.history) if self.history else 0

    def has_enough_water(self) -> bool:
        return (self.get_current_distance() > 10)
