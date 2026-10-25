#!/usr/bin/env python3
import logging
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional, Tuple

import pigpio

from espyresso import config, shot_logger
from espyresso.pwm import PWM

if TYPE_CHECKING:
    from espyresso.bluetooth import BluetoothScale
    from espyresso.boiler import Boiler
    from espyresso.flow import Flow
    from espyresso.ranger import Ranger
    from espyresso.temperature import Temperature
    from espyresso.timer import BrewingTimer


logger = logging.getLogger(__name__)


def remaining_shot_seconds(target_ml: float, current_ml: float, flow_rate: float) -> float:
    """Seconds of shot still to come at the current flow (floored at 0.3 mL/s
    so a stalled meter doesn't claim an endless shot)."""
    return max(0.0, target_ml - current_ml) / max(flow_rate, 0.3)


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
        self.preinfuse_ml = 0.0
        self._stop_reason = ""

        # The end-of-shot path runs from both the pump thread and button
        # callbacks; only the first caller may log the shot.
        self._brew_active = False
        self._brew_lock = threading.Lock()
        self.steaming = False

        self.set_pwm_value(0.75)
        self.pump_thread = threading.Thread(target=self.brew_shot_routine)

    def toggle_pump(self) -> None:
        self.pumping = not self.pumping
        if not self.pumping:
            self.pigpio_pi.write(self.pump_out_gpio, 0)
        else:
            self.reset_started_time()
            self.pigpio_pi.write(self.pump_out_gpio, 1)
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("pump", state="on" if self.pumping else "off")

    def stop_pump(self) -> None:
        self.pigpio_pi.write(self.pump_out_gpio, 0)
        self.boiler.set_pwm_override(None)
        self.pumping = False
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("pump", state="off", source="stop_pump")

    def get_time_since_started_preinfuse(self) -> float:
        if self.stopped_preinfuse and self.started_preinfuse:
            return self.stopped_preinfuse - self.started_preinfuse
        if self.started_preinfuse and self.pumping:
            return time.perf_counter() - self.started_preinfuse
        return 0

    def pulse_pump(self) -> Tuple[bool, Optional[str]]:
        if self.pump_thread.is_alive():
            self.reset()
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
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("pulse_pump", phase="start")

        # Disable automatic BrewingTimer
        self.brewing_timer.disable_automatic_timing()

        started = time.perf_counter()
        self.toggle_pump()
        while (
            self.pumping
            and time.perf_counter() - started < 120
            and not self.temperature.brewhead_ready()
        ):
            self.set_pwm_value(0.5)
            time.sleep(1)
            self.set_pwm_value(0)
            time.sleep(1)

        self.reset()
        if sl is not None:
            sl.log_event(
                "pulse_pump",
                phase="end",
                seconds=time.perf_counter() - started,
                brewhead=self.temperature.get_latest_brewhead_temperature(),
            )

    def pulse_pump_steam(self) -> Tuple[bool, Optional[str]]:
        if self.pump_thread.is_alive():
            self.reset()
            return True, None

        # if not self.ranger.has_enough_water():
        #    return False, "Not enough water"

        self.pump_thread = threading.Thread(target=self.pulse_pump_steam_routine)
        self.reset_started_time()
        self.pump_thread.start()
        return True, None

    def pulse_pump_steam_routine(self) -> None:
        logger.debug("Starting pulse pump steam routine!")
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("steam", phase="start")

        # Disable automatic BrewingTimer
        self.brewing_timer.disable_automatic_timing()

        started = time.perf_counter()
        self.steaming = True
        self.temperature.set_steam_temp()
        self.boiler.turn_on_boiler()
        refill = config.STEAM_REFILL_PWM
        if refill > 0:
            self.toggle_pump()

        while self.steaming and time.perf_counter() - started < config.STEAM_SECONDS:
            if refill > 0:
                self.set_pwm_value(refill)
                time.sleep(0.5)
                self.set_pwm_value(0)
                time.sleep(0.5)
            else:
                time.sleep(0.2)

        self.steaming = False
        self.temperature.set_brew_temp()
        self.reset()
        if sl is not None:
            sl.log_event("steam", phase="end", seconds=time.perf_counter() - started)

    def brew_shot(self) -> Tuple[bool, Optional[str]]:
        if self.pump_thread.is_alive():
            self.reset_brew_routine()
            return True, None

        # The scale may have just been woken: don't wait for the back-off.
        self.bluetooth_scale.request_connect()

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
            return self.reset_brew_routine()

        self._brew_active = True

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

        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("brew", phase="preinfuse_start")

        # Preinfuse until the target volume or time, whichever comes first
        while self.pumping and not (
            self.flow.get_millilitres() > config.PREINFUSE_TARGET_ML
            or (time.perf_counter() - self.started_preinfuse)
            > config.PREINFUSE_MAX_SECONDS
        ):
            self._report_remaining_shot()
            time.sleep(0.1)

        # Stop preinfuse timer
        self.stopped_preinfuse = time.perf_counter()
        self.preinfuse_ml = self.flow.get_millilitres()

        # Start brewing timer
        self.brewing_timer.reset_timer()
        self.brewing_timer.start_timer()

        if sl is not None:
            sl.log_event(
                "brew",
                phase="preinfuse_stop",
                preinfuse_seconds=self.stopped_preinfuse - self.started_preinfuse,
                preinfuse_ml=self.preinfuse_ml,
            )

        self._stop_reason = "button"
        while self.pumping:
            target_grams = config.BREW_TARGET_YIELD_G
            current_grams = self.bluetooth_scale.get_scale_weight()
            current_ml = self.flow.get_millilitres()

            if current_grams >= target_grams:
                self._stop_reason = "weight"
                break
            if not current_grams and current_ml >= self.target_inlet_ml():
                # No scale reading: stop on the flow meter's inlet volume
                self._stop_reason = "volume"
                break

            # Gradually reduce pump pressure before end
            if current_grams > (target_grams - 5):
                self.set_pwm_value(min(0.5, (target_grams - current_grams) / 5))

            time_passed = self.brewing_timer.get_time_since_started()

            # Ramp pump PWM from 0.5 to 0.7 over the first 5 s
            if time_passed < 5:
                self.set_pwm_value(0.5 + 0.2 * (time_passed / 5))
            if time_passed > config.BREW_MAX_SECONDS:
                self._stop_reason = "time"
                break

            self._report_remaining_shot()
            time.sleep(0.05)

        return self.reset_brew_routine()

    def target_inlet_ml(self) -> float:
        """Inlet volume for the target yield: cup + water held by the puck."""
        return (
            config.BREW_TARGET_YIELD_G
            + config.BREW_DOSE_G * config.BREW_RETAINED_ML_PER_G
        )

    def _report_remaining_shot(self) -> None:
        """Tell the controller how much shot is still to come, so it can heat
        for the incoming water (expires on its own if this thread dies)."""
        self.temperature.set_flow_horizon(
            remaining_shot_seconds(
                self.target_inlet_ml(),
                self.flow.get_millilitres(),
                self.flow.get_flow_rate() or 0.0,
            )
        )

    def reset(self) -> None:
        self.steaming = False
        self.stop_pump()
        self.set_pwm_value(0.75)
        self.boiler.set_pwm_override(None)

    def reset_brew_routine(self) -> None:
        with self._brew_lock:
            was_active = self._brew_active
            self._brew_active = False
        self.reset()
        if not was_active:
            return
        self.brewing_timer.stop_timer()
        self.log_shot()
        shot_seconds = self.brewing_timer.get_time_since_started()
        logger.info(
            "shot complete: time=%ss pulses=%s",
            shot_seconds,
            self.flow.get_pulse_count(),
        )
        self.brewing_timer.enable_automatic_timing()
        if not self.stopped_preinfuse:
            self.stopped_preinfuse = time.perf_counter()
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event(
                "brew",
                phase="end",
                reason=self._stop_reason,
                shot_seconds=shot_seconds,
                total_ml=self.flow.get_millilitres(),
                pulses=self.flow.get_pulse_count(),
                final_grams=self.bluetooth_scale.get_scale_weight(),
            )

    def set_pwm_value(self, value: float) -> None:
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        prev = self.pwm.value
        self.pwm.set_value(value)
        sl = shot_logger.get()
        if sl is not None and value != prev:
            sl.log_event("pump_pwm", value=value)

    def log_shot(self) -> None:
        shot_time = self.brewing_timer.get_time_since_started()

        # Skip seemingly invalid shots (time-capped shots are still logged)
        if not (5 < shot_time < config.BREW_MAX_SECONDS + 5):
            return

        preinfuse_seconds = (self.stopped_preinfuse or 0) - (self.started_preinfuse or 0)
        shot_log = (
            f"\n{time.strftime('%Y-%m-%dT%H:%M:%S%z')};"
            f"Time: {shot_time};"
            f"Shot mL: {self.flow.get_millilitres()};"
            f"Shot grams: {self.bluetooth_scale.get_scale_weight()};"
            f"Preinfuse s: {preinfuse_seconds:.1f};"
            f"Preinfuse mL: {self.preinfuse_ml:.1f};"
        )
        with open(config.SHOT_STAT_FILE, "a") as f:
            f.write(shot_log)
