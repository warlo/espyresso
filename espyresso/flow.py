#!/usr/bin/env python3
import logging
import time
from typing import TYPE_CHECKING, Optional

import pigpio

if TYPE_CHECKING:
    from pigpio import pi

    from espyresso.utils import WaveQueue

logger = logging.getLogger(__name__)


class Flow:
    def __init__(self, pigpio_pi: "pi", flow_in_gpio: int, flow_queue: "WaveQueue"):
        logger.debug("Flow initializing")
        self.pigpio_pi = pigpio_pi
        self.flow_in_gpio = flow_in_gpio
        self.pigpio_pi.set_mode(self.flow_in_gpio, pigpio.INPUT)
        self.pigpio_pi.callback(
            self.flow_in_gpio, pigpio.RISING_EDGE, self.pulse_callback
        )

        self.counts_per_liter = 2100  # Original 1925

        self.flow_queue = flow_queue

        self.pulse_start: float = time.perf_counter()
        self.pulse_count: int = 0

        self.last_pulse_count: int = 0
        self.last_pulse_time: Optional[float] = None

    def reset_pulse_count(self) -> None:
        self.pulse_count = 0
        self.last_pulse_count = 0
        self.pulse_start = time.perf_counter()
        self.flow_queue.clear()

    def pulse_callback(self, gpio: int, level: int, tick: int) -> None:

        self.last_pulse_count = self.pulse_count
        self.pulse_count += 1
        if ml_per_sec := self.get_millilitres_per_sec():
            logger.debug("Flow pulse with ml per sec: {ml_per_sec}")
            self.flow_queue.add_to_queue(ml_per_sec)
        self.last_pulse_time = time.perf_counter()

    def get_time_since_last_pulse(self) -> Optional[float]:
        if not self.last_pulse_time:
            return None
        return time.perf_counter() - self.last_pulse_time

    def get_pulse_count(self) -> int:
        return self.pulse_count

    def get_litres(self) -> float:
        return self.get_pulse_count() / self.counts_per_liter

    def get_litres_diff(self) -> float:
        pulse_count = self.get_pulse_count()
        pulse_diff = pulse_count - self.last_pulse_count

        return pulse_diff / self.counts_per_liter

    def get_millilitres(self) -> float:
        return self.get_litres() * 1000

    def get_millilitres_diff(self) -> float:
        return self.get_litres_diff() * 1000

    def get_millilitres_per_sec(self) -> Optional[float]:
        if not self.last_pulse_time:
            return None

        current_time = time.perf_counter()
        time_diff = current_time - self.last_pulse_time

        return max(self.get_millilitres_diff() / time_diff, 0)
