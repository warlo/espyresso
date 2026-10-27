"""Flow meter calibration against the scale (tools/calibrate_flow.py).

Water can't be compressed and the boiler is full, so once the flow is
steady every gram the meter lets into the boiler leaves through the group:
the scale under it weighs what the meter counted. Comparing rates (slopes)
rather than totals makes the scale's Bluetooth delay irrelevant.
"""
from typing import List, NamedTuple, Sequence, Tuple

# The meter is on the cold side (the water tank, ~20 C).
INLET_WATER_DENSITY = 0.998  # g/mL

Sample = Tuple[float, float]  # (seconds, value)


class Step(NamedTuple):
    pulse_rate: float  # pulses per second
    grams_per_pulse: float


def slope(samples: Sequence[Sample]) -> float:
    """Least-squares slope of value over time."""
    n = len(samples)
    if n < 2:
        raise ValueError("need at least two samples")
    mean_t = sum(t for t, _ in samples) / n
    mean_v = sum(v for _, v in samples) / n
    var = sum((t - mean_t) ** 2 for t, _ in samples)
    if var == 0:
        raise ValueError("samples have no time spread")
    return sum((t - mean_t) * (v - mean_v) for t, v in samples) / var


def _window(samples: Sequence[Sample], start: float, end: float) -> List[Sample]:
    return [(t, v) for t, v in samples if start <= t <= end]


def measure_step(pulses: Sequence[Sample], grams: Sequence[Sample], start: float, end: float) -> Step:
    """One steady stretch: ``pulses`` are (time, pulses so far), ``grams``
    (time, scale reading)."""
    pulse_rate = slope(_window(pulses, start, end))
    gram_rate = slope(_window(grams, start, end))
    return Step(pulse_rate=pulse_rate, grams_per_pulse=gram_rate / pulse_rate)


def step_windows(marks: Sequence[Tuple[str, float]], settle: float, trim: float) -> List[Tuple[float, float]]:
    """Steady stretches from pump ("on", t) / ("off", t) marks: skip
    ``settle`` seconds after on and ``trim`` before off."""
    windows = []
    on = None
    for kind, t in marks:
        if kind == "on":
            on = t
        elif kind == "off" and on is not None:
            if t - trim > on + settle:
                windows.append((on + settle, t - trim))
            on = None
    return windows


def table(steps: Sequence[Step]) -> Tuple[Tuple[float, ...], Tuple[float, ...]]:
    """(pulse rates, mL per pulse), sorted by rate, for espyresso.flow."""
    ordered = sorted(steps, key=lambda s: s.pulse_rate)
    rates = tuple(round(s.pulse_rate, 3) for s in ordered)
    ml = tuple(round(s.grams_per_pulse / INLET_WATER_DENSITY, 4) for s in ordered)
    return rates, ml
