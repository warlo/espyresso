"""Flow profiles for the simulator, from the logged Pi shots (Jan-May 2026):
preinfusion always ran the 7 s limit at ~1.4 mL/s, then ~30 s at ~0.95 mL/s
(median 39 mL inlet per shot)."""
from typing import Iterable, Optional, Tuple

from espyresso.pump import remaining_shot_seconds
from espyresso.sim.closedloop import FlowFn
from espyresso.temperature import Temperature

PREINFUSE_SECONDS, PREINFUSE_FLOW = 7.0, 1.4
BREW_SECONDS, BREW_FLOW = 30.0, 0.95
SHOT_SECONDS = PREINFUSE_SECONDS + BREW_SECONDS
SHOT_ML = PREINFUSE_SECONDS * PREINFUSE_FLOW + BREW_SECONDS * BREW_FLOW


def _shot(s: float) -> Tuple[float, float]:
    """(flow, mL so far) at s seconds into a shot."""
    if s < PREINFUSE_SECONDS:
        return PREINFUSE_FLOW, s * PREINFUSE_FLOW
    return BREW_FLOW, PREINFUSE_SECONDS * PREINFUSE_FLOW + (s - PREINFUSE_SECONDS) * BREW_FLOW


def pi_shots(starts: Iterable[float], heat_budget: bool = True) -> FlowFn:
    """Shots run by the Pi's brew routine, which reports the remaining shot
    time to the controller (the in-shot heat budget) unless disabled."""
    starts = sorted(starts)

    def flow(t: float, temperature: Temperature) -> Tuple[float, Optional[float]]:
        for t0 in starts:
            s = t - t0
            if 0 <= s < SHOT_SECONDS:
                rate, ml = _shot(s)
                remaining = remaining_shot_seconds(SHOT_ML, ml, rate) if heat_budget else None
                return rate, remaining
        return 0.0, None

    return flow


def manual_shots(starts: Iterable[float]) -> FlowFn:
    """Shots pulled on the machine's own switch: the Pi only sees the flow."""
    return pi_shots(starts, heat_budget=False)


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
