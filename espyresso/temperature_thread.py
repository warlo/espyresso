#!/usr/bin/env python3

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

from espyresso import config
from espyresso.pcontroller import PController

# from espyresso.pid import PID
from espyresso.tsic import TsicInputChannel

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from pigpio import pi

    from espyresso.boiler import Boiler
    from espyresso.flow import Flow


class TemperatureThread(threading.Thread):
    def __init__(
        self,
        *args,
        pigpio_pi: "pi",
        boiler: "Boiler",
        flow: "Flow",
        get_started_time: Callable,
        add_to_queue: Callable,
        **kwargs,
    ):
        self.get_started_time = get_started_time

        self.boiler = boiler
        self.flow = flow

        self.tsic = TsicInputChannel(pigpio_pi=pigpio_pi, gpio=config.TSIC_GPIO)

        # self.pid = PID()
        # self.pid.set_pid_gains(config.KP, config.KI, config.KD)
        # self.pid.set_integrator_limits(config.IMIN, config.IMAX)
        self.pcontroller = PController(initial_temperature=22.0)

        self._stop_event = threading.Event()

        self.add_to_queue = add_to_queue

        self.lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def update_boiler_value(self, pid_value: float) -> None:

        flow_ml_per_sec = self.flow.get_millilitres_per_sec() or 0
        flow_term = min(flow_ml_per_sec / 10, 0.25)

        value = pid_value + flow_term
        logger.debug(
            f"Updating boiler: value {value}; pid {pid_value}; flow_term {flow_term}"
        )
        self.boiler.set_value(value)

    def run(self):
        with self.tsic:
            prev_timestamp = None
            while not self._stop_event.is_set():
                if (
                    time.perf_counter() - self.get_started_time()
                    > config.TURN_OFF_SECONDS
                    and self.boiler.get_boiling()
                ):
                    # Turn off boiler after 10 minutes
                    self.boiler.toggle_boiler()

                with self.tsic._measure_waiting:
                    self.tsic._measure_waiting.wait(5)

                latest_measurement = self.tsic.measurement

                if (
                    prev_timestamp == latest_measurement.seconds_since_epoch
                    or latest_measurement.degree_celsius is None
                ):
                    logger.warning(
                        f"Undefined or no new temperature measurement: "
                        f"{prev_timestamp}, {latest_measurement}"
                    )
                    continue

                prev_timestamp = latest_measurement.seconds_since_epoch

                temp = latest_measurement.degree_celsius
                heater_value, temp_tuple = self.pcontroller.update(temp)
                self.update_boiler_value(heater_value)

                lock = threading.RLock()
                lock.acquire()
                self.add_to_queue(temp_tuple)
                lock.release()

                logger.debug(
                    f"Temp: {round(temp, 2)} - PID {self.pcontroller}: {heater_value}"
                )

    def stop(self):
        logger.debug("temperature_thread stopping")
        self.boiler.set_value(0)
        self.tsic.stop()
        self._stop_event.set()
        logger.debug("temperature_thread stopped")
