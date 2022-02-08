#!/usr/bin/env python3
import logging
import time
from typing import TYPE_CHECKING, Optional

import pigpio

from espyresso import config

if TYPE_CHECKING:
    from pigpio import pi

    from espyresso.utils import WaveQueue

logger = logging.getLogger(__name__)


class Flow:
    def __init__(self, pigpio_pi: "pi", flow_queue: "WaveQueue"):
        logger.debug("Flow initializing")
        self.pigpio_pi = pigpio_pi
        self.flow_in_gpio = config.FLOW_IN_GPIO
        self.pigpio_pi.set_mode(self.flow_in_gpio, pigpio.INPUT)
        self.pigpio_pi.callback(
            self.flow_in_gpio, pigpio.RISING_EDGE, self.pulse_callback
        )

        self.counts_per_liter = 2100  # Original 1925

        self.flow_queue = flow_queue

        self.pulse_start: float = time.perf_counter()
        self.pulse_count: int = 0

        self.last_pulse_count: int = 0
        self.prev_pulse_time: Optional[float] = None
        self.newest_pulse_time: Optional[float] = None

    def reset_pulse_count(self) -> None:
        self.pulse_count = 0
        self.last_pulse_count = 0
        self.pulse_start = time.perf_counter()
        self.flow_queue.clear()

    def pulse_callback(self, gpio: int, level: int, tick: int) -> None:

        self.last_pulse_count = self.pulse_count
        self.pulse_count += 1
        ml_per_sec = self.get_millilitres_per_sec()
        self.prev_pulse_time, self.newest_pulse_time = (
            self.newest_pulse_time,
            time.perf_counter(),
        )

        if ml_per_sec:
            logger.debug(f"Flow pulse with ml per sec: {ml_per_sec}")
            self.flow_queue.add_to_queue(tuple((ml_per_sec,)))

    def get_time_since_last_pulse(self) -> Optional[float]:
        if not self.newest_pulse_time:
            return None
        return time.perf_counter() - self.newest_pulse_time

    def get_pulse_count(self) -> int:
        return self.pulse_count

    def get_litres(self) -> float:
        return self.get_pulse_count() / self.counts_per_liter

    def get_litres_diff(self) -> float:
        return 1 / self.counts_per_liter

    def get_millilitres(self) -> float:
        return self.get_litres() * 1000

    def get_millilitres_diff(self) -> float:
        return self.get_litres_diff() * 1000

    def get_millilitres_per_sec(self) -> Optional[float]:
        if not self.prev_pulse_time or not self.newest_pulse_time:
            return None

        # Give 0 if over 1 sec since last pulses
        if time.perf_counter() - self.newest_pulse_time > 1:
            return 0

        time_diff = self.newest_pulse_time - self.prev_pulse_time

        return max(self.get_millilitres_diff() / time_diff, 0)
