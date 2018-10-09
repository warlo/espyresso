#!/usr/bin/python3

"""
Examples of how to use the TSIC 206/306 temperature reading class
on a Raspberry PI.
"""

import pigpio
import signal
import time
import sys
from tsic import TsicInputChannel, Measurement
from pid import PID
from boiler import Boiler
from display import Display

TSIC_GPIO = 24
PWM_GPIO = 13

TARGET_TEMP = 93.0
#TARGET_TEMP = 50
KP = 0.08
KI = 0.05
KD = 0.90
IMIN = 0.0
IMAX = 1.0

class Espyresso():
    def __init__(self):
        self.gpio = pigpio.pi()

        self.pid = PID()
        self.pid.set_pid_gains(KP, KI, KD)
        self.pid.set_integrator_limits(IMIN, IMAX)

        self.display = Display()

        self.boiler = Boiler(self.gpio, PWM_GPIO)
        self.tsic = TsicInputChannel(pigpio_pi=self.gpio, gpio=TSIC_GPIO)
        self.temp = 0
        self.running = True

    def update(self):
        with self.tsic:
            while self.running:
                time.sleep(0.2)
                latest_temp = self.tsic.measurement
                print('test', latest_temp)
                if latest_temp == Measurement.UNDEF:
                    pass
                else:
                    self.temp = latest_temp.degree_celsius
                    pid_value = self.pid.update(TARGET_TEMP - self.temp, self.temp)
                    self.boiler.set_value(pid_value)
                    self.display.draw_degrees('{:.1f}'.format(self.temp))
                    #print(pid_value)
                    print('{:.1f}C'.format(self.temp))
            self.boiler.set_value(0)
            self.gpio.stop()

    def quit(self):
        self.boiler.set_value(0)
        self.gpio.stop()
        self.display.stop()

    def signal_handler(self, sig, frame):
        print('You pressed CTRL-C!')
        self.running = False
        time.sleep(1)
        sys.exit(0)

if __name__ == '__main__':
    espyresso = Espyresso()
    signal.signal(signal.SIGINT, espyresso.signal_handler)
    espyresso.update()
