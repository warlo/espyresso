#!/usr/bin/env python3

import logging
import signal
import sys
import threading
import time
import traceback

import pigpio

import config
from flow import Flow
from boiler import Boiler
from buttons import Buttons
from display import Display
from pid import PID

from pump import Pump
from temperature_thread import TemperatureThread


class Espyresso:
    def __init__(self):
        self.started_time = 0

        try:
            self.pigpio_pi = pigpio.pi()
        except Exception as e:
            if not config.DEBUG:
                raise e

        self.flow = Flow(pigpio_pi=self.pigpio_pi, flow_in_gpio=config.FLOW_IN_GPIO)
        self.boiler = Boiler(
            pigpio_pi=self.pigpio_pi,
            pwm_gpio=config.BOILER_PWM_GPIO,
            reset_started_time=self.reset_started_time,
        )
        self.pump = Pump(
            pigpio_pi=self.pigpio_pi,
            boiler=self.boiler,
            pump_pwm_gpio=config.PUMP_PWM_GPIO,
            pump_out_gpio=config.PUMP_OUT_GPIO,
            reset_started_time=self.reset_started_time,
        )
        self.started_time = time.time()

        self.display = Display(
            get_started_time=self.get_started_time,
            target_temp=config.TARGET_TEMP,
            boiler=self.boiler,
            pump=self.pump,
        )

        self.pid = PID()
        self.pid.set_pid_gains(config.KP, config.KI, config.KD)
        self.pid.set_integrator_limits(config.IMIN, config.IMAX)

        self.temperature_thread = TemperatureThread(
            started_time=self.started_time,
            pigpio_pi=self.pigpio_pi,
            display=self.display,
            boiler=self.boiler,
            pid=self.pid,
        )

        self.buttons = Buttons(
            pigpio_pi=self.pigpio_pi,
            boiler=self.boiler,
            pump=self.pump,
            display=self.display,
            button_one=config.BUTTON_ONE_GPIO,
            button_two=config.BUTTON_TWO_GPIO,
        )

        self.running = True

    def reset_started_time(self):
        self.started_time = time.time()

    def get_started_time(self):
        return self.started_time

    def start(self):
        self.reset_started_time()

        self.display.start()
        self.temperature_thread.start()

        threading.Semaphore(0).acquire()

    def stop(self):
        self.temperature_thread.stop()
        self.display.stop()
        self.boiler.set_pwm_override(0)
        self.boiler.set_value(0)
        self.running = False
        time.sleep(1)
        self.pigpio_pi.stop()
        sys.exit(0)

    def signal_handler(self, sig, frame):
        if sig == 2:
            print("You pressed CTRL-C!", sig)
        if sig == 15:
            print("SIGTERM - Killing gracefully!")
        self.stop()


def handler(signum, frame):
    """Why is systemd sending sighups? I DON'T KNOW."""
    logging.warning(f"Got a {signum} signal. Doing nothing")


if __name__ == "__main__":
    espyresso = Espyresso()
    try:
        signal.signal(signal.SIGHUP, handler)
        signal.signal(signal.SIGINT, espyresso.signal_handler)
        signal.signal(signal.SIGTERM, espyresso.signal_handler)
        espyresso.start()
    except Exception as e:
        logging.warning(f"EXCEPTION:{e}")
        logging.warning(traceback.format_exc())
        espyresso.stop()
