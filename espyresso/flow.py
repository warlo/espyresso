#!/usr/bin/env python3
import logging
import threading
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

        self.learning_mode = True
        self.total_volume: float = 0.0
        self.pulse_count = 0

        self.flow_queue = flow_queue

        self.pulse_start: float = time.perf_counter()

        self.prev_pulse_time: Optional[float] = None
        self.newest_pulse_time: Optional[float] = None
        self.lock = threading.RLock()

    def reset_pulse_count(self) -> None:
        self.total_volume = 0.0
        self.pulse_count = 0
        self.prev_pulse_time = None
        self.newest_pulse_time = None
        self.pulse_start = time.perf_counter()
        self.flow_queue.clear()

    def pulse_callback(self, gpio: int, level: int, tick: int) -> None:

        # Skip sub 20ms erratic pulses
        current_time = time.perf_counter()
        if (
            self.newest_pulse_time
            and current_time - self.newest_pulse_time < config.FLOW_METER_DEBOUNCE_TIME
        ):
            logger.warning("Skipping sub 20ms flow pulse")
            self.newest_pulse_time = current_time
            return None

        self.pulse_count += 1
        self.prev_pulse_time, self.newest_pulse_time = (
            self.newest_pulse_time,
            time.perf_counter(),
        )

        pulse_rate = self.get_pulse_rate()
        mls = self.get_mls_per_pulse(pulse_rate)
        flow_rate = self.get_flow_rate()

        if not flow_rate or not mls:
            return

        logger.info(f"Pulse rate, mls, flow_rate: {pulse_rate} {mls} {flow_rate}")
        logger.debug(f"Flow pulse with ml per sec: {flow_rate}")

        self.total_volume += mls
        average_rate = self.total_volume / (self.newest_pulse_time - self.pulse_start)

        self.flow_queue.add_to_queue(tuple((flow_rate, average_rate)))

    def get_time_since_last_pulse(self) -> Optional[float]:
        if not self.newest_pulse_time:
            return None
        return time.perf_counter() - self.newest_pulse_time

    def get_pulse_count(self) -> int:
        return self.pulse_count

    def get_millilitres(self) -> float:
        return self.total_volume

    def get_flow_rate(self) -> Optional[float]:
        pulse_rate = self.get_pulse_rate()

        return pulse_rate * (self.get_mls_per_pulse(pulse_rate) or 0)

    def get_pulse_rate(self) -> float:
        if not self.prev_pulse_time or not self.newest_pulse_time:
            return 0

        time_since_pulse = self.get_time_since_last_pulse()
        if time_since_pulse and time_since_pulse > 0.5:
            return 0

        pulse_rate = 1 / (self.newest_pulse_time - self.prev_pulse_time)
        return pulse_rate

    @staticmethod
    def get_mls_per_pulse(pulse_rate: float) -> Optional[float]:
        pulse_rates = [
            0.755,
            1.006,
            1.257,
            1.508,
            1.759,
            2.010,
            2.261,
            2.512,
            2.763,
            3.014,
            3.265,
            3.516,
            3.767,
            4.018,
            4.269,
            4.520,
            4.771,
            5.022,
            5.273,
            5.524,
            5.775,
        ]
        ml_per_pulse = [
            0.884,
            0.688,
            0.591,
            0.539,
            0.506,
            0.484,
            0.470,
            0.464,
            0.466,
            0.469,
            0.473,
            0.477,
            0.477,
            0.472,
            0.467,
            0.466,
            0.466,
            0.469,
            0.471,
            0.473,
            0.475,
        ]
        interval = (pulse_rates[-1] - pulse_rates[0]) / (len(pulse_rates) - 1)

        # interpolate to get flowrate
        index = int(round((pulse_rate - pulse_rates[0]) / interval))
        if index < 0:
            return None
        if index >= len(pulse_rates) - 1:
            return ml_per_pulse[-1]
        return (
            ml_per_pulse[index]
            + (ml_per_pulse[index + 1] - ml_per_pulse[index])
            * (pulse_rate - pulse_rates[index])
            / interval
        )
