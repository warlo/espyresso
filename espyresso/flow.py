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


# Flow-meter calibration table. Module-level immutable so they aren't
# re-allocated on every pulse (this used to allocate two 21-float lists
# inside get_mls_per_pulse, which is called twice per pulse_callback
# during a shot at ~60 Hz).
_PULSE_RATES = (
    0.755, 1.006, 1.257, 1.508, 1.759, 2.010, 2.261, 2.512, 2.763, 3.014,
    3.265, 3.516, 3.767, 4.018, 4.269, 4.520, 4.771, 5.022, 5.273, 5.524, 5.775,
)
_ML_PER_PULSE = (
    0.884, 0.688, 0.591, 0.539, 0.506, 0.484, 0.470, 0.464, 0.466, 0.469,
    0.473, 0.477, 0.477, 0.472, 0.467, 0.466, 0.466, 0.469, 0.471, 0.473, 0.475,
)
_PULSE_INTERVAL = (_PULSE_RATES[-1] - _PULSE_RATES[0]) / (len(_PULSE_RATES) - 1)


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

        self.prev_pulse_time: float = 0.0
        self.prev_change_time: float = 0.0

        self.first_half_period: Optional[float] = None
        self.second_half_period: Optional[float] = None

    def reset_pulse_count(self) -> None:
        self.total_volume = 0.0
        self.pulse_count = 0
        self.prev_pulse_time = 0.0
        self.prev_change_time = 0.0
        self.first_half_period = None
        self.second_half_period = None
        self.pulse_start = time.perf_counter()
        self.flow_queue.clear()

    def pulse_callback(self, gpio: int, level: int, tick: int) -> None:

        # Skip sub 20ms erratic pulses
        current_time = time.perf_counter()
        if (
            self.prev_change_time
            and current_time - self.prev_change_time < config.FLOW_METER_DEBOUNCE_TIME
        ):
            # Expected behaviour (pump vibration), not a warning. Demoted
            # to DEBUG so the log isn't flooded ~20×/sec during a shot.
            logger.debug("Skipping sub 20ms flow pulse")
            self.prev_change_time = current_time
            return None

        self.pulse_count += 1

        self.first_half_period, self.second_half_period = (
            self.second_half_period,
            current_time - self.prev_pulse_time,
        )

        pulse_rate = self.get_pulse_rate_for_volume()
        ml_per_pulse = self.get_mls_per_pulse(pulse_rate)
        flow_rate = self.get_flow_rate()

        self.prev_pulse_time = current_time

        if not flow_rate or not ml_per_pulse:
            return

        # Both at DEBUG: a brew shot fires ~60 pulses/sec and previously
        # wrote ~60 INFO lines/sec to disk plus formatted an f-string for
        # each. With %s-style lazy formatting nothing is built unless
        # DEBUG logging is enabled.
        logger.debug(
            "pulse rate=%s ml/pulse=%s flow_rate=%s",
            pulse_rate, ml_per_pulse, flow_rate,
        )

        self.total_volume += ml_per_pulse / 2.0
        average_rate = self.total_volume / (self.prev_pulse_time - self.pulse_start)

        self.flow_queue.add_to_queue((flow_rate, average_rate))

    def get_pulse_count(self) -> int:
        return self.pulse_count

    def get_millilitres(self) -> float:
        return self.total_volume

    def get_flow_rate(self) -> Optional[float]:
        if not self.second_half_period:
            pulse_rate = 0.0
        elif not self.first_half_period:
            pulse_rate = 0.5 / self.second_half_period
        else:
            time_since_last_pulse = time.perf_counter() - self.prev_pulse_time
            pulse_rate = 1 / (
                max(time_since_last_pulse, self.first_half_period)
                + self.second_half_period
            )

        return pulse_rate * (self.get_mls_per_pulse(pulse_rate) or 0)

    def get_pulse_rate_for_volume(
        self,
    ) -> float:
        if not self.second_half_period:
            return 0

        if not self.first_half_period:
            pulse_rate = 0.5 / self.second_half_period
        else:
            pulse_rate = 1 / (self.first_half_period + self.second_half_period)
        return pulse_rate

    @staticmethod
    def get_mls_per_pulse(pulse_rate: float) -> Optional[float]:
        # interpolate to get flowrate
        index = int(round((pulse_rate - _PULSE_RATES[0]) / _PULSE_INTERVAL))
        if index < 0:
            return None
        if index >= len(_PULSE_RATES) - 1:
            return _ML_PER_PULSE[-1]
        return (
            _ML_PER_PULSE[index]
            + (_ML_PER_PULSE[index + 1] - _ML_PER_PULSE[index])
            * (pulse_rate - _PULSE_RATES[index])
            / _PULSE_INTERVAL
        )
