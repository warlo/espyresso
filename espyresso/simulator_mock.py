import logging
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


class ButtonOneSimulator(PigpioSimulator):
    name = "button_one"

    def __init__(self, espyresso_mock, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print(espyresso_mock)
        self.espyresso_mock = espyresso_mock
        espyresso_mock.read = self.read
        self.read_started = None

    def read(self, gpio):
        if not self.read_started:
            self.read_started = time.perf_counter()
            return True

        print("READING", gpio)
        if time.perf_counter() - self.read_started > 0.25:
            return False
        else:
            return True

    def run(self):

        while SIMULATOR_RUNNING:
            print("BUTTON")
            input_action = input("Button action: ")
            if input_action == "1":
                print("BUTTON 1 pusehd")
                self.callback(0, 0, 0)
            if input_action == "2":
                print("BUTTON 2 pusehd")
                config.BREW_SETPOINT = 135.0
                config.TARGET_TEMP = 135.0
                # self.callback(0, 0, 0)
            time.sleep(0.1)


class FlowSimulator(PigpioSimulator):
    name = "flow"

    def run(self):
        time.sleep(10)
        last_flow = time.perf_counter()
        while SIMULATOR_RUNNING:
            time.sleep(0.3)
            self.callback(0, 0, 0)
            if time.perf_counter() - last_flow > 10:
                time.sleep(10)
                last_flow = time.perf_counter()


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


def get_callback(espyresso_mock):
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

        if gpio == config.BUTTON_ONE_GPIO:
            button_one_sim = ButtonOneSimulator(espyresso_mock, gpio, edge, callback)
            button_one_sim.start()
            pass

    return gpio_callback


def stop_threads():
    global SIMULATOR_RUNNING
    SIMULATOR_RUNNING = False
    logger.debug("STOPPING SIMULATOR")


espyresso_mock = MagicMock()
espyresso_mock.callback = get_callback(espyresso_mock)
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

        temp_increase_per_sec = 2.33333333
        temp_decrease_per_sec = 1
        hz = 5
        time.sleep(1 / hz)

        self.current_temp += (
            self.boiler.pwm.value * temp_increase_per_sec / hz
            - temp_decrease_per_sec / hz
        )

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
