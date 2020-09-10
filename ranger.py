#!/usr/bin/env python3
import collections
import statistics
import threading
import time

import pigpio


class Ranger(threading.Thread):
    def __init__(
        self,
        *args,
        pigpio_pi=None,
        ranger_trigger_out_gpio=None,
        ranger_echo_in_gpio=None,
        **kwargs
    ):
        self.pigpio_pi = pigpio_pi
        self.ranger_echo_in_gpio = ranger_echo_in_gpio
        self.ranger_trigger_out_gpio = ranger_trigger_out_gpio

        self.pigpio_pi.set_mode(self.ranger_echo_in_gpio, pigpio.INPUT)
        self.pigpio_pi.set_mode(self.ranger_trigger_out_gpio, pigpio.OUTPUT)

        self.pigpio_pi.callback(self.ranger_echo_in_gpio, pigpio.RISING_EDGE, self.rise)
        self.pigpio_pi.callback(
            self.ranger_echo_in_gpio, pigpio.FALLING_EDGE, self.fall
        )
        self.running = True
        self.done = threading.Event()

        self.history = collections.deque(maxlen=10)
        self.high = 0
        self.low = 0
        super().__init__(*args, **kwargs)

    def rise(self, gpio, level, tick):
        self.high = tick

    def fall(self, gpio, level, tick):
        self.low = tick - self.high
        self.done.set()

    def run(self):
        while self.running:
            self.done.clear()
            self.pigpio_pi.gpio_trigger(self.ranger_trigger_out_gpio, 50, 1)
            if self.done.wait(timeout=5):
                distance = self.low / 58.0 / 100.0
                self.history.append(distance)

            time.sleep(0.5)

    def stop(self):
        self.running = False

    def get_current_distance(self):
        return statistics.median(self.history)
