#!/usr/bin/env python3
import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional, Tuple

import pigpio

from espyresso import config
from espyresso.pwm import PWM

if TYPE_CHECKING:
    from espyresso.bluetooth import BluetoothScale
    from espyresso.boiler import Boiler
    from espyresso.flow import Flow
    from espyresso.ranger import Ranger
    from espyresso.temperature import Temperature
    from espyresso.timer import BrewingTimer


logger = logging.getLogger(__name__)


class Pump:
    def __init__(
        self,
        pigpio_pi: pigpio.pi,
        bluetooth_scale: "BluetoothScale",
        boiler: "Boiler",
        temperature: "Temperature",
        flow: "Flow",
        reset_started_time: Callable[[], None],
        brewing_timer: "BrewingTimer",
        ranger: "Ranger",
        pumping: bool = False,
    ) -> None:
        self.pigpio_pi = pigpio_pi
        self.bluetooth_scale = bluetooth_scale
        self.boiler = boiler
        self.temperature = temperature
        self.flow = flow
        self.pump_out_gpio = config.PUMP_OUT_GPIO
        self.pigpio_pi.set_mode(self.pump_out_gpio, pigpio.OUTPUT)

        self.pwm = PWM(pigpio_pi, config.PUMP_PWM_GPIO, 1000)
        self.pumping = pumping
        self.reset_started_time = reset_started_time

        self.started_brew: Optional[float] = None
        self.stopped_brew: Optional[float] = None
        self.brewing_timer = brewing_timer
        self.ranger = ranger

        self.started_preinfuse: Optional[float] = None
        self.stopped_preinfuse: Optional[float] = None

        self.set_pwm_value(0.75)
        self.pump_thread = threading.Thread(target=self.brew_shot_routine)

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

    def pulse_pump(self) -> Tuple[bool, Optional[str]]:
        if self.pump_thread.is_alive():
            self.reset_routine()
            return True, None

        if not self.ranger.has_enough_water():
            return False, "Not enough water"

        if not self.boiler.boiling:
            return False, "Not boiling"

        self.pump_thread = threading.Thread(target=self.pulse_pump_routine)
        self.reset_started_time()
        self.pump_thread.start()
        return True, None

    def pulse_pump_routine(self) -> None:
        logger.debug("Starting pulse pump routine!")

        # Disable automatic BrewingTimer
        self.brewing_timer.disable_automatic_timing()

        started = time.perf_counter()
        self.toggle_pump()
        while (
            self.pumping
            and time.perf_counter() - started < 120
            and self.temperature.get_latest_brewhead_temperature() < 80
        ):
            self.set_pwm_value(0.5)
            time.sleep(1)
            self.set_pwm_value(0)
            time.sleep(1)

        self.stop_pump()
        self.set_pwm_value(0.75)

    def brew_shot(self) -> Tuple[bool, Optional[str]]:
        if self.pump_thread.is_alive():
            self.reset_routine()
            return True, None

        if not self.ranger.has_enough_water():
            return False, "Not enough water"

        if not self.boiler.boiling:
            return False, "Not boiling"

        self.pump_thread = threading.Thread(target=self.brew_shot_routine)
        self.reset_started_time()
        self.pump_thread.start()
        return True, None

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

        while self.pumping:
            # current_ml = self.flow.get_millilitres()
            target_grams = 35
            current_grams = self.bluetooth_scale.get_scale_weight()

            # 36 ml in cup, and 30 ml error in puck / pressure
            if current_grams >= target_grams:
                break

            # Gradually reduce pump pressure before end
            if current_grams > (target_grams - 5):
                self.set_pwm_value(min(0.3, (target_grams - current_grams) / 5))
                break

            time_passed = self.brewing_timer.get_time_since_started()

            # Gradually increase pump PWM to 100% over 5sec
            if time_passed < 5:
                self.set_pwm_value(0.5 + 0.2 * (time_passed / 5))
            if time_passed > 45:
                return self.reset_routine()

            time.sleep(0.05)

        return self.reset_routine()

    def reset_routine(self) -> None:
        self.stop_pump()
        self.brewing_timer.stop_timer()
        self.log_shot()
        self.set_pwm_value(0.75)
        self.boiler.set_pwm_override(None)
        logger.info(f"Time for shot {self.brewing_timer.get_time_since_started()}")
        logger.info(f"Pulse count for shot {self.flow.get_pulse_count()}")
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
        shot_time = self.brewing_timer.get_time_since_started()

        # Skip seemingly invalid shots
        if not (5 < shot_time < 45):
            return

        preinfuse_ml = (self.stopped_preinfuse or 0) - (self.started_preinfuse or 0)
        shot_log = (
            f"\n{time.strftime('%Y-%m-%dT%H:%M:%S%z')};"
            f"Time: {shot_time};"
            f"Shot mL {self.flow.get_millilitres()};"
            f"Preinfuse mL: {preinfuse_ml};"
        )
        with open(config.SHOT_STAT_FILE, "a") as f:
            f.write(shot_log)
