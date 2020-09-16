#!/usr/bin/env python3

import logging
import signal
import threading
import time
import traceback

import config
from pid import PID
from tsic import Measurement, TsicInputChannel


class TemperatureThread(threading.Thread):
    def __init__(
        self,
        *args,
        pigpio_pi=None,
        boiler=None,
        pump=None,
        display=None,
        pid=None,
        get_started_time=None,
        **kwargs,
    ):
        self.get_started_time = get_started_time

        self.boiler = boiler
        self.pump = pump
        self.display = display

        self.pid = pid

        self.tsic = TsicInputChannel(pigpio_pi=pigpio_pi, gpio=config.TSIC_GPIO)

        self.running = True

        self.lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def run(self):
        with self.tsic:
            prev_timestamp = None
            while self.running:
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
                    print("UNDEF", latest_measurement)
                    continue

                prev_timestamp = latest_measurement.seconds_since_epoch

                temp = latest_measurement.degree_celsius
                pid_value = self.pid.update(config.TARGET_TEMP - temp, temp)
                self.boiler.set_value(pid_value)

                lock = threading.RLock()
                lock.acquire()
                self.display.add_to_queue(latest_measurement.degree_celsius)
                lock.release()

                if config.DEBUG:
                    pass
                    print(f"Temp: {round(temp, 2)} - PID: {pid_value}")

    def stop(self):
        self.running = False
        self.boiler.set_value(0)


def handler(signum, frame):
    """Why is systemd sending sighups? I DON'T KNOW."""
    logging.warning(f"Got a {signum} signal. Doing nothing")


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGHUP, handler)

        temperature_thread = TemperatureThread()
        signal.signal(signal.SIGINT, temperature_thread.signal_handler)
        signal.signal(signal.SIGTERM, temperature_thread.signal_handler)
        temperature_thread.run()
    except Exception as e:
        logging.warning(f"EXCEPTION:{e}")
        logging.warning(traceback.format_exc())
