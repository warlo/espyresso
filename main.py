#!/usr/bin/env python3

import logging
import os
import signal
import sys
import threading
import time
import traceback

import pigpio

import config
from boiler import Boiler
from buttons import Buttons
from display import Display
from flow import Flow
from pid import PID
from pump import Pump
from ranger import Ranger
from temperature_thread import TemperatureThread


class Espyresso:
    def __init__(self, pigpio_pi=None):
        self.started_time = 0

        self.pigpio_pi = pigpio_pi
        if not self.pigpio_pi:
            self.pigpio_pi = pigpio.pi()

        self.flow = Flow(pigpio_pi=self.pigpio_pi, flow_in_gpio=config.FLOW_IN_GPIO)
        self.boiler = Boiler(
            pigpio_pi=self.pigpio_pi,
            pwm_gpio=config.BOILER_PWM_GPIO,
            reset_started_time=self.reset_started_time,
        )
        self.ranger = Ranger(
            pigpio_pi=self.pigpio_pi,
            ranger_echo_in_gpio=config.RANGER_ECHO_IN,
            ranger_trigger_out_gpio=config.RANGER_TRIGGER_OUT,
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
            ranger=self.ranger,
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
            turn_off_system=self.turn_off_system,
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
        self.ranger.start()

        threading.Semaphore(0).acquire()

    def stop(self):
        self.temperature_thread.stop()
        self.display.stop()
        self.boiler.set_pwm_override(0)
        self.boiler.set_value(0)
        self.running = False
        time.sleep(1)
        self.pigpio_pi.stop()

    def exit(self):
        self.stop()
        sys.exit(0)

    def turn_off_system(self):
        os.system("shutdown now -h")

    def signal_handler(self, sig, frame):
        if sig == 2:
            print("You pressed CTRL-C!", sig)
        if sig == 15:
            print("SIGTERM - Killing gracefully!")
        self.exit()


def handler(signum, frame):
    """Why is systemd sending sighups? I DON'T KNOW."""
    logging.warning(f"Got a {signum} signal. Doing nothing")


if __name__ == "__main__":
    if not config.DEBUG:
        espyresso = Espyresso()
    else:
        from mock import Mock

        espyresso = Espyresso(pigpio_pi=Mock())
    try:
        signal.signal(signal.SIGHUP, handler)
        signal.signal(signal.SIGINT, espyresso.signal_handler)
        signal.signal(signal.SIGTERM, espyresso.signal_handler)
        espyresso.start()
    except Exception as e:
        logging.warning(f"EXCEPTION:{e}")
        logging.warning(traceback.format_exc())
        espyresso.exit()
