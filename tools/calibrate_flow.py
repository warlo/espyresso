#!/usr/bin/env python3
"""Calibrate the flow meter against the Bluetooth scale. Run on the Pi with
the app stopped:

    sudo systemctl stop espyresso
    sudo python3 tools/calibrate_flow.py open    # no portafilter, a jug on the scale
    sudo python3 tools/calibrate_flow.py puck    # portafilter with a spent puck, cup on the scale
    sudo systemctl start espyresso

Runs the pump at several powers and compares the meter's pulses with the
grams arriving on the scale (espyresso/flow_calibration.py). The heater
stays off throughout (the app is stopped). The pump is switched off on any
exit, Ctrl-C, SIGTERM or SIGHUP. Raw samples and results go to
log/flowcal-<time>.json.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Tuple

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import pigpio  # noqa: E402

from espyresso import config  # noqa: E402
from espyresso import flow_calibration as fc  # noqa: E402
from espyresso.bluetooth import _spawn_scale_process  # noqa: E402
from espyresso.flow import Flow  # noqa: E402
from espyresso.pwm import PWM  # noqa: E402
from espyresso.utils import WaveQueue  # noqa: E402

PLANS = {
    # Through the open group: ~4-8 mL/s, about 350 mL in all.
    "open": dict(powers=(0.5, 0.6, 0.7, 0.85, 1.0), seconds=10.0),
    # Through a spent puck: shot-like flow at pressure, little left to dissolve.
    "puck": dict(powers=(0.5, 0.6, 0.7, 0.85, 1.0), seconds=15.0),
}
PAUSE = 3.0
SETTLE, TRIM = 3.0, 1.0


class Pump:
    def __init__(self, pi: Any) -> None:
        self.pi = pi
        self.pwm = PWM(pi, config.PUMP_PWM_GPIO, 1000)
        pi.set_mode(config.PUMP_OUT_GPIO, pigpio.OUTPUT)

    def on(self, power: float) -> None:
        self.pwm.set_value(power)
        self.pi.write(config.PUMP_OUT_GPIO, 1)

    def off(self) -> None:
        self.pwm.set_value(0)
        self.pi.write(config.PUMP_OUT_GPIO, 0)


def main(plan_name: str) -> None:
    if subprocess.run(["systemctl", "is-active", "--quiet", "espyresso"]).returncode == 0:
        sys.exit("espyresso is running: sudo systemctl stop espyresso first")
    plan = PLANS[plan_name]
    pi = pigpio.pi()
    if not pi.connected:
        sys.exit("pigpiod is not running")
    pump = Pump(pi)
    pump.off()

    def stop(signum: int, _frame: Any) -> None:
        pump.off()
        sys.exit(f"stopped by signal {signum}; pump off")

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, stop)

    flow = Flow(pi, WaveQueue(0, 3, X_MIN=0, X_MAX=10, Y_MIN=0, Y_MAX=10))
    scale = _spawn_scale_process()
    grams: List[Tuple[float, float]] = []
    connected = threading.Event()
    t0 = time.perf_counter()

    def read_scale() -> None:
        for line in iter(scale.stdout.readline, ""):
            parts = line.split()
            if parts == ["link", "connected"]:
                connected.set()
            elif len(parts) == 2 and parts[0] == "w":
                grams.append((time.perf_counter() - t0, float(parts[1])))

    threading.Thread(target=read_scale, daemon=True).start()
    try:
        print("waiting for the scale (wake it if it is asleep) ...", flush=True)
        if not connected.wait(120):
            sys.exit("the scale did not connect")
        time.sleep(2.0)
        pulses: List[Tuple[float, float]] = []
        marks: List[Tuple[str, float]] = []
        done = threading.Event()

        def sample() -> None:
            while not done.is_set():
                pulses.append((time.perf_counter() - t0, flow.edges / 2.0))
                time.sleep(0.1)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        for power in plan["powers"]:
            print(f"pump at {power:.2f} for {plan['seconds']:.0f} s", flush=True)
            marks.append(("on", time.perf_counter() - t0))
            pump.on(power)
            time.sleep(plan["seconds"])
            pump.off()
            marks.append(("off", time.perf_counter() - t0))
            time.sleep(PAUSE)
        done.set()
        sampler.join()
    finally:
        pump.off()
        scale.terminate()

    results: List[Dict[str, float]] = []
    steps = []
    for power, (start, end) in zip(plan["powers"], fc.step_windows(marks, SETTLE, TRIM)):
        try:
            step = fc.measure_step(pulses, grams, start, end)
        except ValueError as e:
            print(f"power {power:.2f}: no usable data ({e})")
            continue
        steps.append(step)
        results.append(dict(power=power, pulse_rate=step.pulse_rate, grams_per_pulse=step.grams_per_pulse,
                            grams_per_second=step.pulse_rate * step.grams_per_pulse))
        print(f"power {power:.2f}: {step.pulse_rate:5.2f} pulses/s, {step.pulse_rate * step.grams_per_pulse:5.2f} g/s, "
              f"{step.grams_per_pulse:.4f} g/pulse")
    rates, ml = fc.table(steps)
    print("table: rates", rates, "mL/pulse", ml)
    out = os.path.join(ROOT, "log", time.strftime(f"flowcal-{plan_name}-%Y%m%d-%H%M%S.json"))
    with open(out, "w") as f:
        json.dump(dict(plan=plan_name, marks=marks, pulses=pulses, grams=grams, results=results,
                       table=dict(rates=rates, ml_per_pulse=ml)), f)
    print("saved", out)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in PLANS:
        sys.exit(f"usage: {sys.argv[0]} {'|'.join(PLANS)}")
    main(sys.argv[1])
