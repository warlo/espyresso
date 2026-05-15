#!/usr/bin/env python3

import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

from espyresso import config, shot_logger
from espyresso.pcontroller import PController

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
        **kwargs: Any,
    ) -> None:
        self.get_started_time = get_started_time

        self.boiler = boiler
        self.flow = flow

        self.tsic = TsicInputChannel(
            pigpio_pi=pigpio_pi, gpio=config.TSIC_GPIO
        )  # type: ignore

        # self.pid = PID()
        # self.pid.set_pid_gains(config.KP, config.KI, config.KD)
        # self.pid.set_integrator_limits(config.IMIN, config.IMAX)

        initial_temperature = self.tsic.measure_once(
            timeout=5
        ).degree_celsius  # type: ignore

        self.prev_timestamp = time.perf_counter()
        logger.warning("INITIAL TEMP: %s", str(initial_temperature))

        if not initial_temperature:
            initial_temperature = 22.0
        self.pcontroller = PController(
            initial_temperature=initial_temperature,
            flow=self.flow,
        )
        self.temp_queue = temp_queue
        self.temp_queue.set_labels(
            [
                "shellTemp",
                "elementTemp",
                "waterTemp",
                "bodyTemp",
                "brewHeadTemp",
                "modeledSensorTemp",
                "temperature",
            ]
        )

        self.lock = threading.RLock()

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

    def update_boiler_value(self, pid_value: float) -> None:

        value = pid_value
        logger.debug(f"Updating boiler: value {value}; pcontroller {pid_value}")
        self.boiler.set_value(value)

    def start(self) -> None:
        self.tsic.start(callback=self.callback)  # type: ignore

    def callback(self, measurement: Measurement) -> None:
        if (
            time.perf_counter() - self.get_started_time() > config.TURN_OFF_SECONDS
            and self.boiler.get_boiling()
        ):
            # Turn off boiler after 10 minutes
            self.boiler.turn_off_boiler()

        if (
            self.prev_timestamp == measurement.seconds_since_epoch
            or measurement.degree_celsius is None
            or measurement.seconds_since_epoch is None
        ):
            logger.warning(
                f"Undefined or no new temperature measurement: "
                f"{self.prev_timestamp}, {measurement}"
            )
            sl = shot_logger.get()
            if sl is not None:
                sl.log_event("tsic_drop", repr=str(measurement))
            return

        self.prev_timestamp = measurement.seconds_since_epoch

        temp = measurement.degree_celsius
        heater_value, temp_tuple = self.pcontroller.update(
            temperature=temp, boiling=self.boiler.get_boiling()
        )
        self.update_boiler_value(heater_value)

        if config.LOG_POWER:
            self.log_power(temp, self.prev_timestamp, heater_value)

        sl = shot_logger.get()
        if sl is not None:
            sl.log_tick(
                raw_temp=temp,
                heater=heater_value,
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

        with self.lock:
            self.temp_queue.add_to_queue(temp_tuple)

        logger.debug(f"Temp: {round(temp, 2)} - PID {self.pcontroller}: {heater_value}")

    def log_power(self, temp: float, timestamp: float, heater_value: float) -> None:
        with open(config.LOG_POWER_FILE, "a+") as f:
            f.write(f"{temp},{timestamp},{heater_value}\n")

    def stop(self) -> None:
        logger.debug("temperature_thread stopping")
        self.boiler.set_value(0)
        self.tsic.stop()  # type: ignore
        logger.debug("temperature_thread stopped")
