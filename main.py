#!/usr/bin/env python3

"""
Examples of how to use the TSIC 206/306 temperature reading class
on a Raspberry PI.
"""
import logging

import pigpio
import signal
import time
import sys
from tsic import TsicInputChannel, Measurement
from pid import PID
from boiler import Boiler
from display import Display

DEBUG = False

TSIC_GPIO = 24
PWM_GPIO = 13

TARGET_TEMP = 95.0
KP = 0.075
KI = 0.06
KD = 0.90
IMIN = 0.0
IMAX = 1.0


class Espyresso:
    def __init__(self):
        self.gpio = pigpio.pi()

        self.pid = PID()
        self.pid.set_pid_gains(KP, KI, KD)
        self.pid.set_integrator_limits(IMIN, IMAX)

        self.display = Display(TARGET_TEMP)

        self.boiler = Boiler(self.gpio, PWM_GPIO)
        self.tsic = TsicInputChannel(pigpio_pi=self.gpio, gpio=TSIC_GPIO)
        self.temp = 0
        self.running = True

    def update(self):
        with self.tsic:
            while self.running:
                time.sleep(0.2)
                latest_temp = self.tsic.measurement
                if latest_temp == Measurement.UNDEF:
                    if DEBUG:
                        print("UNDEF TEMP!")
                else:
                    self.temp = latest_temp.degree_celsius
                    pid_value = self.pid.update(TARGET_TEMP - self.temp, self.temp)
                    self.boiler.set_value(pid_value)
                    self.display.draw(self.temp)
                    if DEBUG:
                        print(f"Temp: {round(self.temp, 2)} - PID: {pid_value}")

    def signal_handler(self, sig, frame):
        if sig == 2:
            print("You pressed CTRL-C!", sig)
        if sig == 15:
            print("SIGTERM - Killing gracefully!")
        self.running = False
        time.sleep(1)
        self.boiler.set_value(0)
        self.display.stop()
        time.sleep(1)
        sys.exit(0)


def handler(signum, frame):
    """Why is systemd sending sighups? I DON'T KNOW."""
    logging.warning("Got a {} signal. Doing nothing".format(signum))


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGHUP, handler)

        espyresso = Espyresso()
        signal.signal(signal.SIGINT, espyresso.signal_handler)
        signal.signal(signal.SIGTERM, espyresso.signal_handler)
        espyresso.update()
    except Exception as e:
        logging.warning(f"EXCEPTION:{e}")
