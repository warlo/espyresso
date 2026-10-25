"""Flow profiles for the simulator. Shots follow the median of the logged
Pi shots with a puck (Jan-Mar 2026), with the flow meter's halving
corrected: a fast fill at the preinfusion pump power, then extraction."""
from typing import Iterable, Optional, Tuple

from espyresso import config
from espyresso.pump import remaining_shot_seconds
from espyresso.sim.closedloop import FlowFn
from espyresso.temperature import Temperature

# The default recipe: 18 g in, 36 g out in 28 s takes about 66 mL in (the
# puck keeps ~30 mL, as measured in 2022).
SHOT_SECONDS, SHOT_ML = 28.0, 66.0


# Median inlet flow of 15 logged shots with a puck (Jan-Mar 2026, the meter's
# halving corrected): (seconds from pump start, mL/s). Filling the headspace
# and wetting the puck at the preinfusion pump power, pressure building,
# then extraction as the puck erodes.
SHOT_SHAPE = ((0.0, 3.8), (2.0, 4.2), (5.0, 3.1), (7.0, 1.9), (10.0, 1.4), (15.0, 1.6), (20.0, 1.8))
# Without preinfusion the pump starts at brew power: a faster fill (open-group
# flow at 0.70 is about 5.4 mL/s), then the same extraction.
SHOT_SHAPE_NO_PREINFUSION = ((0.0, 5.4), (4.0, 2.5), (6.0, 1.4), (11.0, 1.6), (16.0, 1.8))
# The fill ends when the flow drops to extraction; what comes after it is
# what reaches the cup.
FILL_SECONDS = SHOT_SHAPE[3][0]
# The Pi's brew routine pauses the pump this long after the fill (a bloom);
# a Pi shot lasts PI_SHOT_SECONDS from pump start.
BLOOM_SECONDS = config.BREW_BLOOM_SECONDS
PI_SHOT_SECONDS = SHOT_SECONDS + BLOOM_SECONDS


def recipe_shot(
    starts: Iterable[float],
    inlet_ml: float = SHOT_ML,
    seconds: float = SHOT_SECONDS,
    preinfuse: bool = True,
    heat_budget: bool = True,
    bloom: float = 0.0,
) -> FlowFn:
    """Shots with the logged flow shape, the extraction phase scaled so
    ``inlet_ml`` arrives in ``seconds`` of pumping. ``bloom`` pauses the pump
    that long after the fill, so the shot lasts ``seconds + bloom``. The Pi's
    brew routine reports the remaining shot time to the controller (the
    in-shot heat budget) unless ``heat_budget`` is off."""
    shape = SHOT_SHAPE if preinfuse else SHOT_SHAPE_NO_PREINFUSION
    fill_end = FILL_SECONDS if preinfuse else shape[2][0]
    fill_ml = sum(
        (b[0] - a[0]) * a[1] for a, b in zip(shape, shape[1:]) if b[0] <= fill_end
    )
    tail = [(t, r) for t, r in shape if t >= fill_end]
    tail_ml = sum((b[0] - a[0]) * a[1] for a, b in zip(tail, tail[1:])) + tail[-1][1] * (seconds - tail[-1][0])
    scale = max(0.0, inlet_ml - fill_ml) / tail_ml
    starts = sorted(starts)

    def pumped_at(s: float) -> float:
        r = [rate for t, rate in shape if t <= s][-1]
        return r * scale if s >= fill_end else r

    def rate_at(s: float) -> float:
        if s < fill_end:
            return pumped_at(s)
        return 0.0 if s < fill_end + bloom else pumped_at(s - bloom)

    def flow(t: float, temperature: Temperature) -> Tuple[float, Optional[float]]:
        for t0 in starts:
            s = t - t0
            if 0 <= s < seconds + bloom:
                rate = rate_at(s)
                ml = sum(rate_at(x * 0.1) * 0.1 for x in range(int(s / 0.1)))
                return rate, (remaining_shot_seconds(inlet_ml, ml, rate) if heat_budget else None)
        return 0.0, None

    return flow


def pi_shots(starts: Iterable[float], heat_budget: bool = True) -> FlowFn:
    """Shots of the default recipe run by the Pi's brew routine."""
    return recipe_shot(starts, heat_budget=heat_budget, bloom=BLOOM_SECONDS)


def manual_shots(starts: Iterable[float]) -> FlowFn:
    """Shots pulled on the machine's own switch: the Pi only sees the flow."""
    return recipe_shot(starts, heat_budget=False)


def preheat_then_shot(preheat_at: float, shot_at: float, flow_rate: float = 1.5) -> FlowFn:
    """The Pi's preheat routine (pulses until the brew head is ready, max
    120 s; ~1.5 mL/s on average) followed by a Pi shot."""
    state = {"done": False}
    shot = pi_shots([shot_at])

    def flow(t: float, temperature: Temperature) -> Tuple[float, Optional[float]]:
        if preheat_at <= t and not state["done"]:
            if t - preheat_at >= 120 or temperature.brewhead_ready():
                state["done"] = True
            else:
                return flow_rate, None
        return shot(t, temperature)

    return flow


def steam(start_at: float, seconds: float = 120.0, refill_flow: float = 2.0) -> FlowFn:
    """The Pi's steam routine (long press on button one): steam setpoint for
    up to ``seconds``, the pump pulsing 0.5 s on / 0.5 s off to refill the
    boiler (``refill_flow`` mL/s while on, an assumption: the flow at pump
    PWM 0.4 was never measured), then back to the brew setpoint. Uses the
    production set_steam_temp/set_brew_temp. The steam drawn through the
    wand (latent heat) is not modelled."""
    state = {"phase": "before"}

    def flow(t: float, temperature: Temperature) -> Tuple[float, Optional[float]]:
        if state["phase"] == "before" and t >= start_at:
            temperature.set_steam_temp()
            state["phase"] = "steam"
        if state["phase"] == "steam":
            if t >= start_at + seconds:
                temperature.set_brew_temp()
                state["phase"] = "after"
                return 0.0, None
            on = int((t - start_at) / 0.5) % 2 == 0
            return (refill_flow if on else 0.0), None
        return 0.0, None

    return flow
