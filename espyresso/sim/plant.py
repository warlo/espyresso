"""Thermal plant: the machine as the simulator sees it.

Same six-mass structure as espyresso.pcontroller, with every coefficient a
parameter. Two additions the controller does not model:

* ``a_s``: the sensor follows a_s*element + (1-a_s)*shell (the controller
  assumes the element only; the fit puts it about halfway).
* ``eps``: fraction of the flowing water's excess heat the brew head absorbs
  on the way to the puck (the controller assumes 1). Not identifiable from a
  boiler sensor; the puck estimate is ``water - eps*(water - head)``.
"""
import json
import os
from typing import Dict, Optional

from espyresso import config as C

FIT_PATH = os.path.join(os.path.dirname(__file__), "plant_fit.json")

STATE_KEYS = ("elem", "shell", "water", "body", "head", "sensor")


def nominal() -> Dict[str, float]:
    """The controller's own constants, as plant parameters."""
    return dict(
        P_max=C.MAX_BOILER_POWER,
        k_es=C.ELEMENT_SHELL_XFER_COEFF,
        k_w=C.BOILER_WATER_XFER_COEFF_NOFLOW,
        k_bh=C.BOILER_BREWHEAD_XFER_COEFF,
        k_ha=C.BREWHEAD_AMBIENT_XFER_COEFF,
        k_body=C.BOILER_BODY_XFER_COEFF,
        C_body=C.HEAT_CAPACITY_BODY,
        m_shell=C.MASS_BOILER_SHELL,
        m_head=C.MASS_BREW_HEAD + C.MASS_PORTAFILTER,
        V=C.BOILER_VOLUME,
        k_s=C.SENSOR_XFER_COEFF,
        C_s=C.SENSOR_HEAT_CAPACITY,
        eps=1.0,
        a_s=1.0,
        T_amb=C.AMBIENT_TEMPERATURE,
        T_res=C.RESERVOIR_TEMPERATURE,
    )


def fitted(**overrides: float) -> Dict[str, float]:
    """Parameters fitted to this machine's logs. eps defaults to 0.5, the
    middle of the plausible range."""
    with open(FIT_PATH) as f:
        params: Dict[str, float] = json.load(f)
    params["eps"] = 0.5
    params.update(overrides)
    return params


def uniform(temperature: float, head: Optional[float] = None, body: Optional[float] = None) -> Dict[str, float]:
    """Machine at one temperature, e.g. a cold start or a cooled-down restart."""
    state = {k: temperature for k in STATE_KEYS}
    if head is not None:
        state["head"] = head
    if body is not None:
        state["body"] = body
    return state


def at_setpoint(setpoint: float) -> Dict[str, float]:
    """Roughly the settled idle state at a setpoint (from closed-loop runs)."""
    return dict(
        elem=setpoint + 1.6,
        shell=setpoint - 1.3,
        water=setpoint + 0.4,
        body=80.0,
        head=setpoint - 8.0,
        sensor=setpoint + 0.5,
    )


class Plant:
    def __init__(self, params: Dict[str, float], state: Dict[str, float]) -> None:
        self.p = dict(params)
        self.elem = state["elem"]
        self.shell = state["shell"]
        self.water = state["water"]
        self.body = state["body"]
        self.head = state["head"]
        self.sensor = state["sensor"]
        self.puck = self.water

    def step(self, dt: float, heater_w: float, flow: float) -> None:
        p = self.p
        cw = C.SPEC_HEAT_WATER_100
        half = C.SPEC_HEAT_ALUMINIUM * p["m_shell"] / 2.0
        w_flow = flow * (self.water - p["T_res"]) * cw
        h_amb = (self.head - p["T_amb"]) * p["k_ha"]
        s_w = (self.shell - self.water) * p["k_w"] / 2.0
        e_w = (self.elem - self.water) * p["k_w"] / 2.0
        s_h = (self.shell - self.head) * p["k_bh"] / 2.0
        e_h = (self.elem - self.head) * p["k_bh"] / 2.0
        wf_h = p["eps"] * (self.water - self.head) * flow * cw
        e_s = (self.elem - self.shell) * p["k_es"]
        s_b = (self.shell - self.body) * p["k_body"] / 2.0
        e_b = (self.elem - self.body) * p["k_body"] / 2.0
        if flow > 0:
            self.puck = self.water - p["eps"] * (self.water - self.head)
        self.head += dt * (s_h + e_h + wf_h - h_amb) / (C.SPEC_HEAT_BRASS * p["m_head"])
        self.water += dt * (s_w + e_w - w_flow) / (cw * p["V"])
        self.shell += dt * (e_s - s_h - s_w - s_b) / half
        self.elem += dt * (heater_w - e_s - e_h - e_w - e_b) / half
        self.body += dt * (s_b + e_b) / p["C_body"]
        target = p["a_s"] * self.elem + (1.0 - p["a_s"]) * self.shell
        self.sensor += dt * (target - self.sensor) * p["k_s"] / p["C_s"]
