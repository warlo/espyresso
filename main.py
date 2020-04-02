#!/usr/bin/env python3

"""
Examples of how to use the TSIC 206/306 temperature reading class
on a Raspberry PI.
"""
import logging
import traceback

import pigpio
import signal
import time
import sys
from tsic import TsicInputChannel, Measurement
from pid import PID
from boiler import Boiler
from display import Display
from buttons import Buttons

DEBUG = False

TSIC_GPIO = 24
PWM_GPIO = 13
BUTTON_ONE_GPIO = 20
BUTTON_TWO_GPIO = 21

TARGET_TEMP = 94.0
KP = 0.074
KI = 0.06
KD = 0.90
IMIN = 0.0
IMAX = 1.0


class Espyresso:
    def __init__(self):
        self.started_time = 0

        self.gpio = pigpio.pi()
        self.boiler = Boiler(self.gpio, PWM_GPIO, self.reset_started_time)

        self.pid = PID()
        self.pid.set_pid_gains(KP, KI, KD)
        self.pid.set_integrator_limits(IMIN, IMAX)

        self.display = Display(TARGET_TEMP)

        self.tsic = TsicInputChannel(pigpio_pi=self.gpio, gpio=TSIC_GPIO)
        self.buttons = Buttons(
            self.gpio, self.boiler, self.display, BUTTON_ONE_GPIO, BUTTON_TWO_GPIO
        )

        self.running = True

    def reset_started_time(self):
        self.started_time = time.time()

    def run(self):
        with self.tsic:
            self.started_time = time.time()
            prev_timestamp = None
            while self.running:
                if time.time() - self.started_time > 600.0 and self.boiler.boiling:
                    # Show something on display that boiler is soon shutting off
                    # Click button to add another 10 minutes to avoid issues while brewing
                    self.boiler.toggle_boiler()

                with self.tsic._measure_waiting:
                    self.tsic._measure_waiting.wait(5)

                latest_measurement = self.tsic.measurement
                if prev_timestamp == latest_measurement.seconds_since_epoch or latest_measurement == Measurement.UNDEF:
                    print("UNDEF", latest_measurement)
                    continue

                prev_timestamp = latest_measurement.seconds_since_epoch

                temp = latest_measurement.degree_celsius
                pid_value = self.pid.update(TARGET_TEMP - temp, temp)
                self.boiler.set_value(pid_value)
                self.display.draw(temp, self.boiler.boiling, int(600.0 - (time.time() - self.started_time)))

                if DEBUG:
                    print(f"Temp: {round(temp, 2)} - PID: {pid_value}")

    def signal_handler(self, sig, frame):
        if sig == 2:
            print("You pressed CTRL-C!", sig)
        if sig == 15:
            print("SIGTERM - Killing gracefully!")
        self.running = False
        self.boiler.set_value(0)
        time.sleep(1)
        self.display.stop()
        sys.exit(0)


def handler(signum, frame):
    """Why is systemd sending sighups? I DON'T KNOW."""
    logging.warning(f"Got a {signum} signal. Doing nothing")


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGHUP, handler)

        espyresso = Espyresso()
        signal.signal(signal.SIGINT, espyresso.signal_handler)
        signal.signal(signal.SIGTERM, espyresso.signal_handler)
        espyresso.run()
    except Exception as e:
        logging.warning(f"EXCEPTION:{e}")
        logging.warning(traceback.format_exc())
