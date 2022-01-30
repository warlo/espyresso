import logging
import os
import signal
import sys
import time

import pigpio

from espyresso import config
from espyresso.boiler import Boiler
from espyresso.buttons import Buttons
from espyresso.display import Display
from espyresso.flow import Flow
from espyresso.pid import PID
from espyresso.pump import Pump
from espyresso.ranger import Ranger
from espyresso.temperature_thread import TemperatureThread
from espyresso.timer import BrewingTimer
from espyresso.utils import WaveQueue

logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)


class Espyresso:
    def __init__(self, pigpio_pi=None):
        self.started_time = time.perf_counter()

        self.pigpio_pi = pigpio_pi
        if not self.pigpio_pi:
            self.pigpio_pi = pigpio.pi()

        self.flow_queue = WaveQueue(
            0,
            2,
            X_MIN=config.FLOW_X_MIN,
            X_MAX=config.FLOW_X_MAX,
            Y_MIN=config.FLOW_Y_MIN,
            Y_MAX=config.FLOW_Y_MAX,
            steps=5,
        )
        self.flow = Flow(
            pigpio_pi=self.pigpio_pi,
            flow_in_gpio=config.FLOW_IN_GPIO,
            flow_queue=self.flow_queue,
        )
        self.brewing_timer = BrewingTimer(flow=self.flow)

        self.boiler_queue = WaveQueue(
            0,
            100,
            X_MIN=config.BOILER_X_MIN,
            X_MAX=config.BOILER_X_MAX,
            Y_MIN=config.BOILER_Y_MIN,
            Y_MAX=config.BOILER_Y_MAX,
            steps=5,
        )
        self.boiler = Boiler(
            pigpio_pi=self.pigpio_pi,
            boiling=config.DEBUG,
            pwm_gpio=config.BOILER_PWM_GPIO,
            reset_started_time=self.reset_started_time,
            add_to_queue=self.boiler_queue.add_to_queue,
        )
        self.ranger = Ranger(
            pigpio_pi=self.pigpio_pi,
            ranger_echo_in_gpio=config.RANGER_ECHO_IN,
            ranger_trigger_out_gpio=config.RANGER_TRIGGER_OUT,
        )
        self.pump = Pump(
            pigpio_pi=self.pigpio_pi,
            boiler=self.boiler,
            flow=self.flow,
            pump_pwm_gpio=config.PUMP_PWM_GPIO,
            pump_out_gpio=config.PUMP_OUT_GPIO,
            reset_started_time=self.reset_started_time,
            brewing_timer=self.brewing_timer,
        )

        self.pid = PID()
        self.pid.set_pid_gains(config.KP, config.KI, config.KD)
        self.pid.set_integrator_limits(config.IMIN, config.IMAX)

        self.temp_queue = WaveQueue(
            90,
            100,
            X_MIN=config.TEMP_X_MIN,
            X_MAX=config.TEMP_X_MAX,
            Y_MIN=config.TEMP_Y_MIN,
            Y_MAX=config.TEMP_Y_MAX,
            target_y=config.TARGET_TEMP,
        )
        self.temperature_thread = TemperatureThread(
            get_started_time=self.get_started_time,
            pigpio_pi=self.pigpio_pi,
            boiler=self.boiler,
            pid=self.pid,
            add_to_queue=self.temp_queue.add_to_queue,
        )

        self.display = Display(
            get_started_time=self.get_started_time,
            boiler=self.boiler,
            brewing_timer=self.brewing_timer,
            pump=self.pump,
            ranger=self.ranger,
            flow=self.flow,
            wave_queues={
                "temp": self.temp_queue,
                "flow": self.flow_queue,
                "boiler": self.boiler_queue,
            },
        )

        self.buttons = Buttons(
            pigpio_pi=self.pigpio_pi,
            boiler=self.boiler,
            pump=self.pump,
            display=self.display,
            button_one=config.BUTTON_ONE_GPIO,
            button_two=config.BUTTON_TWO_GPIO,
            turn_off_system=self.turn_off_system,
        )

        self.running = True

    def reset_started_time(self) -> None:
        self.started_time = time.perf_counter()

    def get_started_time(self) -> float:
        return self.started_time

    def start(self) -> None:
        self.reset_started_time()

        self.display.start()
        self.temperature_thread.start()
        self.ranger.start()
        self.brewing_timer.start()

        self.display.join()
        self.temperature_thread.join()
        self.ranger.join()
        self.brewing_timer.join()

    def stop(self) -> None:
        self.brewing_timer.stop()
        self.ranger.stop()
        self.temperature_thread.stop()
        self.display.stop()
        self.boiler.stop()

        self.running = False
        time.sleep(1)
        logger.debug("Pigpio stopping")
        self.pigpio_pi.stop()

    def exit(self) -> None:
        self.stop()
        logger.debug("EXITING: Stopped all")
        time.sleep(1)
        try:
            logger.debug("SYS EXIT 0")
            sys.exit(0)
        except Exception:
            logger.exception("Failed exiting")

    def turn_off_system(self):
        self.stop()
        logger.debug("Triggering shutdown")
        os.system("shutdown now -h")

    def signal_handler(self, sig, frame):
        if sig == 2:
            print("You pressed CTRL-C!", sig)
        if sig == 15:
            print("SIGTERM - Killing gracefully!")
        self.exit()


def handler(signum, frame):
    """Why is systemd sending sighups?"""
    logger.warning(f"Got a {signum} signal. Doing nothing")


def run():
    if not config.DEBUG:
        espyresso = Espyresso()
    else:
        from espyresso.simulator_mock import get_espyresso_simulator

        espyresso = get_espyresso_simulator()

    try:
        signal.signal(signal.SIGHUP, handler)
        signal.signal(signal.SIGINT, espyresso.signal_handler)
        signal.signal(signal.SIGTERM, espyresso.signal_handler)
        espyresso.start()
    except Exception:
        logger.exception("EXCEPTION")
        espyresso.exit()
