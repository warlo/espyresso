#!/usr/bin/env python3

import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from espyresso import config, shot_logger
from espyresso.pcontroller import PController, boot_boost_seconds
from espyresso.safety import SafetyGuard

# from espyresso.pid import PID
from espyresso.tsic import Measurement, TsicInputChannel

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from pigpio import pi

    from espyresso.boiler import Boiler
    from espyresso.flow import Flow
    from espyresso.utils import WaveQueue


class Temperature:
    def __init__(
        self,
        *args: Any,
        pigpio_pi: "pi",
        boiler: "Boiler",
        flow: "Flow",
        get_started_time: Callable[[], float],
        temp_queue: "WaveQueue",
        heartbeat: Optional[Callable[[], None]] = None,
        tsic: Optional[TsicInputChannel] = None,
        **kwargs: Any,
    ) -> None:
        self.get_started_time = get_started_time
        # Called after every completed control tick; feeds the watchdog.
        self.heartbeat = heartbeat
        self.guard = SafetyGuard()
        self.last_safety = ""
        self._started = False
        self._had_valid_tick = False
        self._prev_boiling = boiler.get_boiling()

        self.boiler = boiler
        self.flow = flow

        # Injectable so the closed-loop simulator (espyresso/sim) can drive
        # the real control path without hardware.
        self.tsic = tsic or TsicInputChannel(
            pigpio_pi=pigpio_pi, gpio=config.TSIC_GPIO
        )  # type: ignore

        # self.pid = PID()
        # self.pid.set_pid_gains(config.KP, config.KI, config.KD)
        # self.pid.set_integrator_limits(config.IMIN, config.IMAX)

        initial_temperature = self.tsic.measure_once(
            timeout=5
        ).degree_celsius  # type: ignore

        self.prev_timestamp = time.perf_counter()
        logger.info("initial TSIC reading on GPIO %s = %s", config.TSIC_GPIO, initial_temperature)

        # A failed first reading must not start the model at some fallback
        # temperature: the first valid tick re-initialises it (see callback).
        self._needs_resync = not initial_temperature
        if not initial_temperature:
            initial_temperature = config.AMBIENT_TEMPERATURE
        self.pcontroller = PController(
            initial_temperature=initial_temperature,
            flow=self.flow,
        )
        self.temp_queue = temp_queue
        # Labels map 1:1 to the tuple PController.update returns. The
        # last entry (raw sensor reading) is the hero in the header strip
        # and isn't shown in the diagnostic legend.
        self.temp_queue.set_labels(
            [
                "shell",
                "elem",
                "water",
                "body",
                "head",
                "model",
                "tp",
            ]
        )

    def set_steam_temp(self) -> None:
        self.pcontroller.set_target_temp(config.TARGET_STEAM_TEMP)
        self.temp_queue.target_y = config.TARGET_STEAM_TEMP
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("setpoint", target=config.TARGET_STEAM_TEMP, mode="steam")

    def set_brew_temp(self) -> None:
        self.pcontroller.set_target_temp(config.TARGET_TEMP)
        self.temp_queue.target_y = config.TARGET_TEMP
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("setpoint", target=config.TARGET_TEMP, mode="brew")

    def get_latest_brewhead_temperature(self) -> float:
        return self.pcontroller.brewHeadTemp

    def brewhead_ready(self) -> bool:
        return (
            self.pcontroller.brewHeadTemp
            >= self.pcontroller.temp_setpoint - config.BREWHEAD_READY_BELOW_SETPOINT
        )

    def set_flow_horizon(self, seconds: float) -> None:
        self.pcontroller.set_flow_horizon(seconds)

    def update_boiler_value(self, pid_value: float) -> None:

        value = pid_value
        logger.debug("Updating boiler: value %s; pcontroller %s", value, pid_value)
        self.boiler.set_value(value)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.tsic.start(callback=self.callback)  # type: ignore

    def callback(self, measurement: Measurement) -> None:
        try:
            self._control_tick(measurement)
        except Exception:
            # Never leave the element at its last duty after a failed tick.
            logger.exception("control tick failed: heater off")
            self.boiler.force_off()

    def _control_tick(self, measurement: Measurement) -> None:
        if (
            self.prev_timestamp == measurement.seconds_since_epoch
            or measurement.degree_celsius is None
            or measurement.seconds_since_epoch is None
        ):
            logger.warning(
                "Undefined or no new temperature measurement: %s, %s",
                self.prev_timestamp, measurement,
            )
            sl = shot_logger.get()
            if sl is not None:
                sl.log_event("tsic_drop", repr=str(measurement))
            return

        self.prev_timestamp = measurement.seconds_since_epoch

        temp = measurement.degree_celsius
        if not self._had_valid_tick:
            self._had_valid_tick = True
            if self._needs_resync:
                # The model was built from a fallback temperature: start it
                # over, brew head and body included.
                self.pcontroller.reset(temp)
            boost = boot_boost_seconds(temp, self.pcontroller.temp_setpoint)
            self.pcontroller.start_boost(boost)
            logger.info("first reading %.2f C: boost %.2f s", temp, boost)

        boiling = self.boiler.get_boiling()
        if boiling and not self._prev_boiling:
            # Switching the boiler on is the user's acknowledgement of a fault.
            self.guard.clear()
        self._prev_boiling = boiling

        heater_cmd, temp_tuple = self.pcontroller.update(
            temperature=temp, boiling=boiling
        )
        heater_value, safety = self.guard.limit(
            now=time.perf_counter(),
            temperature=temp,
            heater=heater_cmd,
            setpoint=self.pcontroller.temp_setpoint,
            flowing=(self.flow.get_flow_rate() or 0) > 0.3,
        )
        self.last_safety = safety
        if self.guard.fault and boiling:
            logger.error("safety fault: %s; boiler off", self.guard.fault)
            self.boiler.turn_off_boiler()
            self.boiler.fault = self.guard.fault
            self._prev_boiling = False
            sl = shot_logger.get()
            if sl is not None:
                sl.log_event("safety", reason=self.guard.fault, temperature=temp)
        self.update_boiler_value(heater_value)

        if config.LOG_POWER:
            self.log_power(temp, self.prev_timestamp, heater_value)

        sl = shot_logger.get()
        if sl is not None:
            sl.log_tick(
                raw_temp=temp,
                heater=heater_value,
                heater_cmd=heater_cmd,
                safety=safety,
                flow_ml=self.flow.get_millilitres(),
                boiling=self.boiler.get_boiling(),
                pwm_override=self.boiler.pwm_override,
                setpoint=self.pcontroller.temp_setpoint,
                shellTemp=temp_tuple[0],
                elementTemp=temp_tuple[1],
                waterTemp=temp_tuple[2],
                bodyTemp=temp_tuple[3],
                brewHeadTemp=temp_tuple[4],
                modeledSensorTemp=temp_tuple[5],
                **self.pcontroller.diagnostics,
            )

        # deque.append is GIL-atomic; no explicit lock needed for a
        # single-producer, single-consumer rolling buffer.
        self.temp_queue.add_to_queue(temp_tuple)

        # Lazy %s: the formatting (and the round() / repr) only runs when
        # DEBUG logging is actually enabled.
        logger.debug("Temp: %s - PID %s: %s", temp, self.pcontroller, heater_value)

        if self.heartbeat is not None:
            self.heartbeat()

    def log_power(self, temp: float, timestamp: float, heater_value: float) -> None:
        with open(config.LOG_POWER_FILE, "a+") as f:
            f.write(f"{temp},{timestamp},{heater_value}\n")

    def stop(self) -> None:
        logger.debug("temperature_thread stopping")
        # Stop the control callbacks first so no late tick can write a duty
        # after the element has been switched off.
        self.tsic.stop()  # type: ignore
        self.boiler.force_off()
        logger.debug("temperature_thread stopped")
