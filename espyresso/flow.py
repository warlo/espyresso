#!/usr/bin/env python3
import logging
import time
from typing import TYPE_CHECKING, Optional

import pigpio

from espyresso import config
from espyresso.utils import safe_callback

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
# No pulse for this long (or three periods): the water has stopped.
_FLOW_STOPPED_SECONDS = 2.0


def _tick_diff(earlier: int, later: int) -> int:
    """Microseconds between two pigpio ticks (they wrap at 2**32)."""
    return (later - earlier) & 0xFFFFFFFF


class Flow:
    def __init__(self, pigpio_pi: "pi", flow_queue: "WaveQueue"):
        logger.debug("Flow initializing")
        self.pigpio_pi = pigpio_pi
        self.flow_in_gpio = config.FLOW_IN_GPIO
        self.pigpio_pi.set_mode(self.flow_in_gpio, pigpio.INPUT)
        self.pigpio_pi.callback(
            self.flow_in_gpio, pigpio.RISING_EDGE, safe_callback(self.pulse_callback)
        )

        self.learning_mode = True
        self.total_volume: float = 0.0
        # Never reset (unlike total_volume, which restarts every shot): lets
        # the watchdog notice water flowing, e.g. shots pulled on the machine's
        # own switch, to postpone auto-off.
        self.lifetime_ml: float = 0.0
        self.pulse_count = 0

        self.flow_queue = flow_queue

        self.pulse_start: float = time.perf_counter()
        self.prev_tick: Optional[int] = None
        self.prev_pulse_time: float = 0.0
        self.prev_period: Optional[float] = None
        self.last_period: Optional[float] = None

    def reset_pulse_count(self) -> None:
        self.total_volume = 0.0
        self.pulse_count = 0
        self.prev_tick = None
        self.prev_pulse_time = 0.0
        self.prev_period = None
        self.last_period = None
        self.pulse_start = time.perf_counter()
        self.flow_queue.clear()

    def pulse_callback(self, gpio: int, level: int, tick: int) -> None:
        """One rising edge per pulse of the meter. Periods come from pigpio's
        tick (when the edge happened): Python may handle edges late and in
        bursts when the Pi is busy."""
        self.pulse_count += 1
        if self.prev_tick is not None:
            period = _tick_diff(self.prev_tick, tick) / 1e6
            if period > 0:
                self.prev_period, self.last_period = self.last_period, period
        self.prev_tick = tick
        self.prev_pulse_time = time.perf_counter()

        rate = self.get_pulse_rate_for_volume()
        # The first pulse of a run has no rate yet: count it at the typical
        # value; slower than the table goes: its slowest value.
        ml_per_pulse = (self.get_mls_per_pulse(rate) or _ML_PER_PULSE[0]) if rate else _ML_PER_PULSE[-1]
        self.total_volume += ml_per_pulse
        self.lifetime_ml += ml_per_pulse
        average_rate = self.total_volume / max(1e-3, self.prev_pulse_time - self.pulse_start)
        self.flow_queue.add_to_queue((self.get_flow_rate(), average_rate))

    def get_pulse_count(self) -> int:
        return self.pulse_count

    def get_millilitres(self) -> float:
        return self.total_volume

    def get_flow_rate(self) -> float:
        """mL/s, from the recent pulse period; falls off once pulses stop."""
        rate = self.get_pulse_rate_for_volume()
        if not rate:
            return 0.0
        since = time.perf_counter() - self.prev_pulse_time
        if since > max(_FLOW_STOPPED_SECONDS, 3.0 / rate):
            return 0.0
        rate = min(rate, 1.0 / since) if since > 1.0 / rate else rate
        return rate * (self.get_mls_per_pulse(rate) or _ML_PER_PULSE[0])

    def get_pulse_rate_for_volume(self) -> float:
        """Pulses per second over the last two periods."""
        if not self.last_period:
            return 0.0
        if not self.prev_period:
            return 1.0 / self.last_period
        return 2.0 / (self.prev_period + self.last_period)

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
