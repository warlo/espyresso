"""Is the machine ready to brew?

One answer for the screen, button one (flush or brew) and the preheat flush,
from the boiler model and the warm-up's estimate of the group head
(espyresso/warmup.py). READY means a shot pulled now should come out close
to one from a fully warm machine; the thresholds are in espyresso/config.py
and were chosen in simulation on every plant that fits the logs.
"""

import math
from enum import Enum
from typing import Optional

from espyresso import config


class BrewState(str, Enum):
    FAULT = "FAULT"  # safety switched the boiler off
    OFF = "OFF"  # boiler off
    STEAM = "STEAM"  # steam mode
    FLOW = "FLOW"  # water is flowing (shot or flush)
    HEATING = "HEAT"  # boiler below its target
    COOLING = "COOL"  # boiler above its target, e.g. after steaming
    FLUSH = "FLUSH"  # boiler hot, group cold: a flush now helps
    WARMING = "WARM"  # group nearly warm; the warm-up makes up the rest
    READY = "READY"


def brew_state(
    *,
    boiling: bool,
    fault: bool,
    steam: bool,
    flowing: bool,
    group_deficit: float,
    water_from_setpoint: float,
    water_from_target: float,
    previous: Optional[BrewState] = None,
    ready_deficit: Optional[float] = None,
    flush_deficit: Optional[float] = None,
    water_band: Optional[float] = None,
) -> BrewState:
    """``group_deficit``: K the group head is below its temperature on a warm
    machine (inf or NaN when unknown, treated as cold). ``water_from_*``: the
    modelled boiler water minus the brew setpoint, and minus the controller's
    target (the setpoint plus any warm-up offset). ``previous`` is the last
    state: HEAT and COOL are left at half their entry threshold, so a boiler
    hovering at a threshold doesn't make the screen flicker."""
    ready_deficit = config.READY_GROUP_DEFICIT if ready_deficit is None else ready_deficit
    flush_deficit = config.FLUSH_GROUP_DEFICIT if flush_deficit is None else flush_deficit
    band = config.READY_WATER_BAND if water_band is None else water_band
    if math.isnan(group_deficit):
        group_deficit = math.inf

    if fault:
        return BrewState.FAULT
    if not boiling:
        return BrewState.OFF
    if steam:
        return BrewState.STEAM
    if flowing:
        return BrewState.FLOW
    # Below the setpoint itself, not the warm-up's raised target: holding the
    # boiler hot for a cold group is not "still heating".
    if water_from_setpoint < (-band / 2 if previous is BrewState.HEATING else -band):
        return BrewState.HEATING
    # Well above the target, e.g. after steaming; the warm-up easing off its
    # offset stays below this.
    if water_from_target > (band if previous is BrewState.COOLING else 2 * band):
        return BrewState.COOLING
    if group_deficit > flush_deficit:
        return BrewState.FLUSH
    if group_deficit > ready_deficit:
        return BrewState.WARMING
    return BrewState.READY
