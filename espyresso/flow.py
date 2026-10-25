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
            self.flow_in_gpio, pigpio.EITHER_EDGE, safe_callback(self.pulse_callback)
        )

        self.learning_mode = True
        self.total_volume: float = 0.0
        # Never reset (unlike total_volume, which restarts every shot): lets
        # the watchdog notice water flowing, e.g. shots pulled on the machine's
        # own switch, to postpone auto-off.
        self.lifetime_ml: float = 0.0

        self.flow_queue = flow_queue

        self.pulse_start: float = time.perf_counter()
        self.edges = 0
        self.prev_change_tick: Optional[int] = None
        self.prev_edge_tick: Optional[int] = None
        self.prev_pulse_time: float = 0.0
        self.first_half_period: Optional[float] = None
        self.second_half_period: Optional[float] = None

    def reset_pulse_count(self) -> None:
        self.total_volume = 0.0
        self.edges = 0
        self.prev_edge_tick = None
        self.prev_pulse_time = 0.0
        self.first_half_period = None
        self.second_half_period = None
        self.pulse_start = time.perf_counter()
        self.flow_queue.clear()

    def pulse_callback(self, gpio: int, level: int, tick: int) -> None:
        """Each edge of the meter's square wave is half a pulse, as in Tom
        Brazier's firmware (a pin-change interrupt): half the volume, and the
        rate from half-periods. A change within FLOW_METER_DEBOUNCE_TIME of the
        previous one is a bounce from pump vibration. Times are pigpio's ticks
        (when the edge happened): Python may handle edges late on a busy Pi."""
        bounce = (
            self.prev_change_tick is not None
            and _tick_diff(self.prev_change_tick, tick) / 1e6 < config.FLOW_METER_DEBOUNCE_TIME
        )
        self.prev_change_tick = tick
        if bounce:
            return

        if self.prev_edge_tick is not None:
            self.first_half_period, self.second_half_period = (
                self.second_half_period,
                _tick_diff(self.prev_edge_tick, tick) / 1e6,
            )
        self.prev_edge_tick = tick
        self.edges += 1
        self.prev_pulse_time = time.perf_counter()

        rate = self.get_pulse_rate_for_volume()
        # The first edges of a run have no rate yet: count them at the typical
        # value; slower than the table goes: its slowest value.
        ml_per_pulse = (self.get_mls_per_pulse(rate) or _ML_PER_PULSE[0]) if rate else _ML_PER_PULSE[-1]
        self.total_volume += ml_per_pulse / 2.0
        self.lifetime_ml += ml_per_pulse / 2.0
        average_rate = self.total_volume / max(1e-3, self.prev_pulse_time - self.pulse_start)
        self.flow_queue.add_to_queue((self.get_flow_rate(), average_rate))

    @property
    def pulse_count(self) -> int:
        return self.edges // 2

    def get_pulse_count(self) -> int:
        return self.pulse_count

    def get_millilitres(self) -> float:
        return self.total_volume

    def get_flow_rate(self) -> float:
        """mL/s from the last two half-periods; falls off once edges stop."""
        rate = self.get_pulse_rate_for_volume()
        if not rate:
            return 0.0
        since = time.perf_counter() - self.prev_pulse_time
        if since > max(_FLOW_STOPPED_SECONDS, 3.0 / rate):
            return 0.0
        if self.first_half_period and self.second_half_period:
            rate = 1.0 / (max(since, self.first_half_period) + self.second_half_period)
        return rate * (self.get_mls_per_pulse(rate) or _ML_PER_PULSE[0])

    def get_pulse_rate_for_volume(self) -> float:
        """Meter pulses per second from the last two half-periods."""
        if not self.second_half_period:
            return 0.0
        if not self.first_half_period:
            return 0.5 / self.second_half_period
        return 1.0 / (self.first_half_period + self.second_half_period)

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
