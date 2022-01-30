#!/usr/bin/env python3
import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional

import pigpio

from espyresso import config
from espyresso.pwm import PWM

if TYPE_CHECKING:
    from espyresso.boiler import Boiler
    from espyresso.flow import Flow
    from espyresso.timer import BrewingTimer


logger = logging.getLogger(__name__)


class Pump:
    def __init__(
        self,
        pigpio_pi: pigpio.pi,
        boiler: "Boiler",
        flow: "Flow",
        pump_out_gpio: int,
        pump_pwm_gpio: int,
        reset_started_time: Callable,
        brewing_timer: "BrewingTimer",
        pumping=False,
    ):
        self.pigpio_pi = pigpio_pi
        self.boiler = boiler
        self.flow = flow
        self.pump_out_gpio = pump_out_gpio
        self.pigpio_pi.set_mode(self.pump_out_gpio, pigpio.OUTPUT)

        self.pwm = PWM(pigpio_pi, pump_pwm_gpio, 1000)
        self.pumping = pumping
        self.reset_started_time = reset_started_time

        self.started_brew: Optional[float] = None
        self.stopped_brew: Optional[float] = None
        self.brewing_timer = brewing_timer

        self.started_preinfuse: Optional[float] = None
        self.stopped_preinfuse: Optional[float] = None

        self.set_pwm_value(1)
        self.brew_thread = threading.Thread(target=self.brew_shot_routine)

    def toggle_pump(self) -> None:
        self.pumping = not self.pumping
        if not self.pumping:
            self.pigpio_pi.write(self.pump_out_gpio, 0)
        else:
            self.reset_started_time()
            self.pigpio_pi.write(self.pump_out_gpio, 1)

    def stop_pump(self) -> None:
        self.pigpio_pi.write(self.pump_out_gpio, 0)
        self.boiler.set_pwm_override(None)
        self.pumping = False

    def get_time_since_started_preinfuse(self) -> float:
        if self.stopped_preinfuse and self.started_preinfuse:
            return self.stopped_preinfuse - self.started_preinfuse
        if self.started_preinfuse and self.pumping:
            return time.perf_counter() - self.started_preinfuse
        return 0

    def brew_shot(self) -> None:
        if self.brew_thread.is_alive():
            self.brewing_timer.stop_timer()
            self.stop_pump()
        else:
            self.brew_thread = threading.Thread(target=self.brew_shot_routine)
            self.reset_started_time()
            self.brew_thread.start()

    def brew_shot_routine(self) -> None:
        logger.debug("Starting brew shot routine!")

        # If already pumping then reset the routine
        if self.pumping:
            return self.reset_routine()

        # Reset flow meter
        self.flow.reset_pulse_count()

        # Disable automatic BrewingTimer
        self.brewing_timer.disable_automatic_timing()

        # Hard-code boiler to 30% during preinfuse and start pump at 0.5 PWM (2-3 bars?)
        self.set_pwm_value(0.5)
        self.boiler.set_pwm_override(0.30)
        self.toggle_pump()

        # Set started preinfuse time
        self.started_preinfuse = time.perf_counter()
        self.stopped_preinfuse = None

        # Sleep until flow is above 30ml or 7seconds
        while self.pumping and not (
            self.flow.get_millilitres() > 30
            or (time.perf_counter() - self.started_preinfuse) > 7
        ):
            time.sleep(0.1)

        # Stop preinfuse timer
        self.stopped_preinfuse = time.perf_counter()

        # Start brewing timer
        self.brewing_timer.reset_timer()
        self.brewing_timer.start_timer()

        # Hard-code boiler to 25%
        self.boiler.set_pwm_override(0.25)

        while self.pumping and self.flow.get_millilitres() < (30 + 36):
            time_passed = self.brewing_timer.get_time_since_started()

            # Gradually increase pump PWM to 100% over 5sec
            if time_passed < 5:
                self.set_pwm_value(0.5 + 0.5 * (time_passed / 5))
            if time_passed > 45:
                return self.reset_routine()

            time.sleep(0.05)

        return self.reset_routine()

    def reset_routine(self):
        if self.pumping:
            self.toggle_pump()
        self.log_shot()
        self.set_pwm_value(1)
        self.boiler.set_pwm_override(None)
        self.brewing_timer.stop_timer()
        self.brewing_timer.enable_automatic_timing()
        if not self.stopped_preinfuse:
            self.stopped_preinfuse = time.perf_counter()

    def set_pwm_value(self, value: float) -> None:
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)

    def log_shot(self) -> None:
        preinfuse_ml = (self.stopped_preinfuse or 0) - (self.started_preinfuse or 0)
        shot_log = (
            f"\n{time.strftime('%Y-%m-%dT%H:%M:%S%z')};"
            f"Time: {self.brewing_timer.get_time_since_started()};"
            f"Shot mL {self.flow.get_millilitres()};"
            f"Preinfuse mL: {preinfuse_ml};"
        )
        with open(config.SHOT_COUNT_FILE, "a") as f:
            f.write(shot_log)
