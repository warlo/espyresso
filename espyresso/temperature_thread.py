#!/usr/bin/env python3

import logging
import threading
import time

from espyresso import config
from espyresso.tsic import Measurement, TsicInputChannel

logger = logging.getLogger(__name__)


class TemperatureThread(threading.Thread):
    def __init__(
        self,
        *args,
        pigpio_pi=None,
        boiler=None,
        pump=None,
        pid=None,
        get_started_time=None,
        add_to_queue=None,
        **kwargs,
    ):
        self.get_started_time = get_started_time

        self.boiler = boiler
        self.pump = pump

        self.pid = pid

        self.tsic = TsicInputChannel(pigpio_pi=pigpio_pi, gpio=config.TSIC_GPIO)

        self._stop_event = threading.Event()

        self.add_to_queue = add_to_queue

        self.lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def run(self):
        with self.tsic:
            prev_timestamp = None
            while not self._stop_event.is_set():
                if (
                    time.time() - self.get_started_time() > config.TURN_OFF_SECONDS
                    and self.boiler.get_boiling()
                ):
                    # Turn off boiler after 10 minutes
                    self.boiler.toggle_boiler()

                with self.tsic._measure_waiting:
                    self.tsic._measure_waiting.wait(5)

                latest_measurement = self.tsic.measurement
                if (
                    prev_timestamp == latest_measurement.seconds_since_epoch
                    or latest_measurement == Measurement.UNDEF
                ):
                    logger.warning(
                        f"Undefined or no new temperature measurement: "
                        f"{prev_timestamp}, {latest_measurement}"
                    )
                    continue

                prev_timestamp = latest_measurement.seconds_since_epoch

                temp = latest_measurement.degree_celsius
                pid_value = self.pid.update(config.TARGET_TEMP - temp, temp)
                self.boiler.set_value(pid_value)

                lock = threading.RLock()
                lock.acquire()
                self.add_to_queue(latest_measurement.degree_celsius)
                lock.release()

                if config.DEBUG:
                    logger.debug(f"Temp: {round(temp, 2)} - PID: {pid_value}")

    def stop(self):
        logger.debug("temperature_thread stopping")
        self.boiler.set_value(0)
        self.tsic.stop()
        self._stop_event.set()
        logger.debug("temperature_thread stopped")
