"""Warm-up: run the boiler hotter while the group head is still cold.

After a cold start the boiler reaches its setpoint in a few minutes, but the
group head and portafilter (1.6 kg of brass) take much longer, and a cold
group cools the water on its way to the coffee. While the group is cold the
controller is asked to hold the boiler above its setpoint, in proportion to
how far the group is from warm, so an early shot comes out close to one from
a warm machine. The offset fades as the group warms and is exactly zero once
the group is within the dead-band of warm: a warm machine is not affected.

The group isn't measured, so it is estimated with a single thermal mass
coupled to the boiler wall (whose temperature the sensor reads) and to the
room, and warmed by water flowing through it (a preheat flush or a shot). The
estimate starts as warm as the first reading: after a short restart, when the
group may still be warm, that errs towards no offset rather than a hot shot.
"""

import math
from typing import Optional

from espyresso import config


def overdrive(deficit: float, *, gain: float, deadband: float, max_offset: float) -> float:
    """Boiler target offset (K) for a group ``deficit`` K below warm."""
    if not math.isfinite(deficit):
        return 0.0
    return min(max_offset, max(0.0, gain * (deficit - deadband)))


class GroupWarmUp:
    def __init__(
        self,
        *,
        gain: Optional[float] = None,
        deadband: Optional[float] = None,
        max_offset: Optional[float] = None,
        coupling: Optional[float] = None,
        flow_exchange: Optional[float] = None,
    ) -> None:
        self.gain = config.WARMUP_GAIN if gain is None else gain
        self.deadband = config.WARMUP_DEADBAND if deadband is None else deadband
        self.max_offset = config.WARMUP_MAX_OFFSET if max_offset is None else max_offset
        self.coupling = config.WARMUP_GROUP_COUPLING if coupling is None else coupling
        self.flow_exchange = config.WARMUP_FLOW_EXCHANGE if flow_exchange is None else flow_exchange
        self.ambient = config.AMBIENT_TEMPERATURE
        self.ambient_coupling = config.BREWHEAD_AMBIENT_XFER_COEFF
        self.heat_capacity = config.SPEC_HEAT_BRASS * (config.MASS_BREW_HEAD + config.MASS_PORTAFILTER)

        self.group: Optional[float] = None
        self.offset = 0.0
        self._last: Optional[float] = None

    def warm_temperature(self, setpoint: float) -> float:
        """The group's temperature on a machine that has been at ``setpoint``
        for a long time: between the boiler and the room."""
        return (self.coupling * setpoint + self.ambient_coupling * self.ambient) / (
            self.coupling + self.ambient_coupling
        )

    def update(self, now: float, *, boiler: float, water: float, flow_rate: float, setpoint: float) -> float:
        """Advance the group estimate to ``now`` (s) and return the boiler
        target offset (K). ``boiler`` is the sensor reading, ``water`` the
        boiler water (for water flowing through), ``flow_rate`` in mL/s."""
        if not (math.isfinite(boiler) and math.isfinite(now)):
            return self.offset
        if not math.isfinite(water):
            water = boiler
        if self.group is None or self._last is None:
            self.group = boiler
        else:
            dt = max(0.0, now - self._last)
            flow_coupling = self.flow_exchange * max(0.0, flow_rate or 0.0) * config.SPEC_HEAT_WATER_100
            total = self.coupling + self.ambient_coupling + flow_coupling
            settles_at = (
                self.coupling * boiler + self.ambient_coupling * self.ambient + flow_coupling * water
            ) / total
            # Exact for inputs held over the step, so any gap is stable.
            self.group = settles_at + (self.group - settles_at) * math.exp(-dt * total / self.heat_capacity)
        self._last = now
        self.offset = overdrive(
            self.warm_temperature(setpoint) - self.group,
            gain=self.gain,
            deadband=self.deadband,
            max_offset=self.max_offset,
        )
        return self.offset
