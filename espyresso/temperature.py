#!/usr/bin/env python3

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

from espyresso import config
from espyresso.pcontroller import PController

# from espyresso.pid import PID
from espyresso.tsic import Measurement, TsicInputChannel

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from pigpio import pi

    from espyresso.boiler import Boiler
    from espyresso.flow import Flow
    from espyresso.utils import WaveQueue

LOG_POWER_FILE = f"log/power-{time.strftime('%X')}.log"


class Temperature:
    def __init__(
        self,
        *args,
        pigpio_pi: "pi",
        boiler: "Boiler",
        flow: "Flow",
        get_started_time: Callable,
        temp_queue: "WaveQueue",
        **kwargs,
    ):
        self.get_started_time = get_started_time

        self.boiler = boiler
        self.flow = flow

        self.tsic = TsicInputChannel(pigpio_pi=pigpio_pi, gpio=config.TSIC_GPIO)

        # self.pid = PID()
        # self.pid.set_pid_gains(config.KP, config.KI, config.KD)
        # self.pid.set_integrator_limits(config.IMIN, config.IMAX)

        initial_temperature = self.tsic.measure_once(timeout=5).degree_celsius
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

    def get_latest_brewhead_temperature(self) -> float:
        return self.pcontroller.brewHeadTemp

    def update_boiler_value(self, pid_value: float) -> None:

        value = pid_value
        logger.debug(f"Updating boiler: value {value}; pcontroller {pid_value}")
        self.boiler.set_value(value)

    def start(self) -> None:
        self.tsic.start(callback=self.callback)

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
            return

        self.prev_timestamp = measurement.seconds_since_epoch

        temp = measurement.degree_celsius
        heater_value, temp_tuple = self.pcontroller.update(
            temperature=temp, boiling=self.boiler.get_boiling()
        )
        self.update_boiler_value(heater_value)

        if config.LOG_POWER:
            self.log_power(temp, self.prev_timestamp, heater_value)

        self.lock.acquire()
        self.temp_queue.add_to_queue(temp_tuple)
        self.lock.release()

        logger.debug(f"Temp: {round(temp, 2)} - PID {self.pcontroller}: {heater_value}")

    def log_power(self, temp, timestamp, heater_value):
        with open(LOG_POWER_FILE, "a+") as f:
            f.write(f"{temp},{timestamp},{heater_value}\n")

    def stop(self):
        logger.debug("temperature_thread stopping")
        self.boiler.set_value(0)
        self.tsic.stop()
        logger.debug("temperature_thread stopped")
