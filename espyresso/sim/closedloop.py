"""Run the production control path against the plant on a simulated clock.

Everything between the sensor reading and the PWM duty is the real code:
Temperature (control tick, boot boost, safety guard), PController, Boiler and
the Watchdog. Only the hardware is faked: pigpio records the boiler duty, the
TSIC reading comes from the plant, and time comes from the simulation.
"""
import math
import time
import types
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from espyresso import config
from espyresso import pcontroller as pcontroller_module
from espyresso import shot_logger
from espyresso import temperature as temperature_module
from espyresso.boiler import Boiler
from espyresso.safety import Watchdog
from espyresso.sim.plant import Plant, fitted
from espyresso.temperature import Temperature
from espyresso.tsic import Measurement
from espyresso.utils import WaveQueue

TICK = 0.093  # median logged controller period
TSIC_LSB = 200.0 / 2047  # TSIC 306: 11 bits over -50..150 C

# flow(t, temperature) -> (inlet mL/s, seconds of Pi shot remaining or None)
FlowFn = Callable[[float, Temperature], Tuple[float, Optional[float]]]


class Run:
    def __init__(self, rows: List[Dict[str, float]]) -> None:
        self.rows = rows

    def window(self, t0: float, t1: float) -> List[Dict[str, float]]:
        return [r for r in self.rows if t0 <= r["t"] <= t1]

    def max(self, col: str, after: float = -math.inf, before: float = math.inf) -> float:
        return max(r[col] for r in self.rows if after <= r["t"] <= before)

    def first_time(self, pred: Callable[[Dict[str, float]], bool]) -> float:
        return next((r["t"] for r in self.rows if pred(r)), math.inf)

    def at(self, t: float) -> Dict[str, float]:
        return [r for r in self.rows if r["t"] <= t][-1]


class _FakePi:
    connected = True

    def __init__(self) -> None:
        self.boiler_duty = 0.0

    def hardware_PWM(self, gpio: int, freq: int, duty: int) -> None:
        if gpio == config.BOILER_PWM_GPIO:
            self.boiler_duty = duty / 1e6

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *a, **kw: None


class _FakeFlow:
    def __init__(self) -> None:
        self.rate = 0.0
        self.shot_ml = 0.0
        self.lifetime_ml = 0.0

    def get_flow_rate(self) -> float:
        return self.rate

    def get_millilitres(self) -> float:
        return self.shot_ml


class _FakeTsic:
    def __init__(self, first: Measurement) -> None:
        self.first = first

    def measure_once(self, timeout: Any = None) -> Measurement:
        return self.first

    def start(self, callback: Any = None) -> None:
        pass

    def stop(self) -> None:
        pass


_TIMED_MODULES = (pcontroller_module, temperature_module, shot_logger)


@contextmanager
def _sim_clock(clock: List[float]) -> Iterator[None]:
    """Point the control code's ``time.perf_counter`` at the simulated clock."""
    fake = types.SimpleNamespace(perf_counter=lambda: clock[0], strftime=time.strftime)
    saved = [getattr(m, "time") for m in _TIMED_MODULES]
    for m in _TIMED_MODULES:
        setattr(m, "time", fake)
    try:
        yield
    finally:
        for m, original in zip(_TIMED_MODULES, saved):
            setattr(m, "time", original)


def simulate(
    *,
    duration: float,
    start: Dict[str, float],
    params: Optional[Dict[str, float]] = None,
    setpoint: Optional[float] = None,
    flow: Optional[FlowFn] = None,
    first_reading_ok: bool = True,
    stall: Optional[Tuple[float, float]] = None,
    sensor_override: Optional[Callable[[float, float], float]] = None,
    auto_off: bool = True,
    tick: float = TICK,
    log_dir: Optional[str] = None,
    controller_sees_flow: bool = True,
) -> Run:
    """Simulate ``duration`` seconds from the app starting with the machine in
    plant state ``start``. ``stall`` = (t0, t1) stops control callbacks then
    (e.g. a hung pigpio thread). ``sensor_override(t, true_reading)`` replaces
    what the sensor reports (e.g. a detached sensor). ``log_dir`` writes the
    session through the production ShotLogger (simulated time), in the same
    format as the Pi, plus a ``sim`` section in the metadata.
    ``controller_sees_flow=False`` hides the flow meter from the controller
    (no flow feed-forward), like the plain-PID machines in published tests."""
    p = params or fitted()
    plant = Plant(p, start)
    clock = [0.0]
    started = [0.0]
    pi = _FakePi()
    ff = _FakeFlow()
    ctrl_flow = ff if controller_sees_flow else _FakeFlow()
    rows: List[Dict[str, float]] = []

    previous_logger = shot_logger.get()
    with _sim_clock(clock):
        session = shot_logger.init(log_dir) if log_dir else None
        if session is not None:
            meta = shot_logger.collect_metadata()
            meta["sim"] = dict(params=p, start=start, duration=duration, setpoint=setpoint)
            session.write_meta(meta)
        else:
            shot_logger._INSTANCE = None
        boiler = Boiler(pigpio_pi=pi, reset_started_time=lambda: None, add_to_queue=lambda v: None, boiling=True)
        watchdog = Watchdog(
            boiler=boiler,
            pump=None,
            flow=ff,  # type: ignore[arg-type]
            get_started_time=(lambda: started[0]) if auto_off else (lambda: clock[0]),
            reset_started_time=lambda: started.__setitem__(0, clock[0]),
            notify=lambda message: None,
            clock=lambda: clock[0],
        )
        undefined: Measurement = getattr(Measurement, "UNDEF")
        first = Measurement(_quantize(plant.sensor), 0.0) if first_reading_ok else undefined
        temperature = Temperature(
            pigpio_pi=pi,
            boiler=boiler,
            flow=ctrl_flow,  # type: ignore[arg-type]
            get_started_time=lambda: started[0],
            temp_queue=WaveQueue(90, 100, X_MIN=0, X_MAX=10, Y_MIN=0, Y_MAX=10),
            heartbeat=watchdog.heartbeat,
            tsic=_FakeTsic(first),  # type: ignore[arg-type]
        )
        if setpoint is not None:
            temperature.pcontroller.set_target_temp(setpoint)

        next_watchdog = 0.0
        while clock[0] < duration:
            t = clock[0]
            rate, remaining = flow(t, temperature) if flow else (0.0, None)
            if rate > 0 and ff.rate == 0:
                ff.shot_ml = 0.0
            ff.rate = rate
            ff.shot_ml += rate * tick
            ff.lifetime_ml += rate * tick
            if remaining is not None:
                temperature.set_flow_horizon(remaining)

            plant.step(tick, pi.boiler_duty * p["P_max"], rate)
            clock[0] = t + tick

            reading = plant.sensor if sensor_override is None else sensor_override(clock[0], plant.sensor)
            stalled = stall is not None and stall[0] <= clock[0] < stall[1]
            if not stalled:
                temperature.callback(Measurement(_quantize(reading), clock[0]))
            if clock[0] >= next_watchdog:
                watchdog.display_heartbeat()  # the simulated display is always drawing
                watchdog.check()
                next_watchdog = clock[0] + config.WATCHDOG_INTERVAL

            pc = temperature.pcontroller
            rows.append(
                dict(
                    t=clock[0],
                    sensor=reading,
                    duty=pi.boiler_duty,
                    flow=rate,
                    water=plant.water,
                    elem=plant.elem,
                    shell=plant.shell,
                    head=plant.head,
                    puck=plant.puck,
                    m_water=pc.waterTemp,
                    m_head=pc.brewHeadTemp,
                    target=pc.target,
                    # Labels ride along with the numbers.
                    state=temperature.brew_state().value,  # type: ignore[dict-item]
                    safety=temperature.last_safety,  # type: ignore[dict-item]
                    boiling=1.0 if boiler.get_boiling() else 0.0,
                )
            )
        if session is not None:
            session.close()
    shot_logger._INSTANCE = previous_logger
    return Run(rows)


def _quantize(celsius: float) -> float:
    return round(celsius / TSIC_LSB) * TSIC_LSB
