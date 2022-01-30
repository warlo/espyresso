import contextlib
import logging
import math
import random
import threading
import time

import pigpio
from mock import MagicMock, patch

from espyresso import config
from espyresso.app import Espyresso
from espyresso.boiler import Boiler
from espyresso.tsic import Measurement

logger = logging.getLogger(__name__)

SIMULATOR_RUNNING = True


class PigpioSimulator(threading.Thread):
    name: str

    def __init__(self, gpio, edge, callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gpio = gpio
        self.edge = edge
        self.callback = callback
        self._stop_event = threading.Event()

    def run(self):
        while SIMULATOR_RUNNING:
            time.sleep(0.5)
            logger.debug(f"Callback to: {self.name}")
            self.callback(0, 0, 0)

    def stop(self):
        self._stop_event.set()


class FlowSimulator(PigpioSimulator):
    name = "flow"

    def run(self):
        while SIMULATOR_RUNNING:
            time.sleep(0.3)
            # self.callback(0, 0, 0)


class RangerRiseSimulator(PigpioSimulator):
    name = "ranger-rise"

    def run(self):
        while SIMULATOR_RUNNING:
            time.sleep(2)
            self.callback(0, 0, 10)


class RangerFallSimulator(PigpioSimulator):
    name = "ranger-fall"

    def run(self):
        while SIMULATOR_RUNNING:
            time.sleep(2)
            self.callback(0, 0, 5)


def gpio_callback(gpio, edge, callback):
    logger.debug(f"GPIO {gpio}")

    if gpio == config.FLOW_IN_GPIO:
        logger.debug("FLOW gpio")
        flow_sim = FlowSimulator(gpio, edge, callback)
        flow_sim.start()

    if gpio == config.RANGER_ECHO_IN and edge == pigpio.RISING_EDGE:
        ranger_sim = RangerRiseSimulator(gpio, edge, callback)
        ranger_sim.start()

    if gpio == config.RANGER_ECHO_IN and edge == pigpio.FALLING_EDGE:
        ranger_sim = RangerFallSimulator(gpio, edge, callback)
        ranger_sim.start()


def stop_threads():
    global SIMULATOR_RUNNING
    SIMULATOR_RUNNING = False
    logger.debug("STOPPING SIMULATOR")


espyresso_mock = MagicMock()
espyresso_mock.callback = gpio_callback
espyresso_mock.stop = stop_threads


class MeasureWaiting:
    def __init__(self, tsic, boiler: Boiler, *args):
        super().__init__(*args)
        self.tsic = tsic
        self.boiler = boiler

        self.current_temp = 20
        self.preheated = False

    def __enter__(self):
        pass

    def __exit__(self, *args):
        pass

    def wait(self, *args):
        time.sleep(0.2)

        if self.current_temp < 94 and not self.preheated:
            self.current_temp += self.boiler.pwm.value * 0.5 * math.log(95)
        else:
            self.preheated = True
            self.current_temp += -0.2 + ((1 + self.boiler.pwm.value) ** 2 - 1) * 0.6

        self.tsic.return_value.measurement = Measurement(
            self.current_temp, time.perf_counter()
        )


def get_espyresso_simulator():
    with patch("espyresso.temperature_thread.TsicInputChannel") as mocked_cls:
        espyresso = Espyresso(pigpio_pi=espyresso_mock)
        mocked_cls.return_value._measure_waiting = MeasureWaiting(
            mocked_cls, espyresso.boiler
        )
        return espyresso
