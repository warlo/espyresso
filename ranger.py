#!/usr/bin/env python3
import threading
import time

import pigpio


class Ranger:
    def __init__(
        self, pigpio_pi=None, ranger_trigger_out_gpio=None, ranger_echo_in_gpio=None
    ):
        self.pigpio_pi = pigpio_pi
        self.ranger_echo_in_gpio = ranger_echo_in_gpio
        self.ranger_trigger_out_gpio = ranger_trigger_out_gpio

        self.pigpio_pi.set_mode(self.ranger_echo_in_gpio, pigpio.INPUT)
        self.pigpio_pi.set_mode(self.ranger_trigger_out_gpio, pigpio.OUTPUT)

        self.pigpio_pi.callback(self.ranger_echo_in_gpio, pigpio.RISING_EDGE, rise)
        self.pigpio_pi.callback(self.ranger_echo_in_gpio, pigpio.FALLING_EDGE, fall)
        self.done = threading.Event()

        self.current_distance = 0
        self.high = 0
        self.low = 0

    def rise(self, gpio, level, tick):
        self.high = tick

    def fall(self, gpio, level, tick):
        self.low = tick - self.high
        self.done.set()

    def read_distance(self):
        self.done.clear()
        self.pigpio_pi.gpio_trigger(self.ranger_trigger_out_gpio, 50, 1)
        if self.done.wait(timeout=5):
            distance = self.low / 58.0 / 100.0
            self.current_distance = distance

    def get_current_distance(self):
        return self.current_distance
