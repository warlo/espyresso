#!/usr/bin/env python3
import time

import pigpio


class Flow:
    def __init__(self, pigpio_pi=None, flow_in_gpio=None, add_to_queue=None):
        self.pigpio_pi = pigpio_pi
        self.flow_in_gpio = flow_in_gpio
        self.pigpio_pi.set_mode(self.flow_in_gpio, pigpio.INPUT)
        self.pigpio_pi.callback(
            self.flow_in_gpio, pigpio.RISING_EDGE, self.pulse_callback
        )

        self.counts_per_liter = 2112  # Original 1925

        self.flowing = False
        self.add_to_queue = add_to_queue

        self.pulse_start = time.time()
        self.pulse_count = 0

        self.last_time = time.time()
        self.last_pulse_count = 0

    def reset_pulse_count(self):
        self.pulse_count = 0
        self.pulses_start = time.time()

    def pulse_callback(self, gpio, level, tick):
        self.pulse_count += 1
        self.add_to_queue(self.get_millilitres_per_sec())

    def get_pulse_count(self):
        return self.pulse_count

    def get_litres(self):
        return self.get_pulse_count() / self.counts_per_liter

    def get_litres_diff(self):
        pulse_count = self.get_pulse_count()
        pulse_diff = pulse_count - self.last_pulse_count
        self.last_pulse_count = pulse_count 

        return pulse_diff / self.counts_per_liter

    def get_millilitres(self):
        return self.get_litres() * 1000

    def get_millilitres_diff(self):
        return self.get_litres_diff() * 1000

    def get_millilitres_per_sec(self):
        current_time = time.time()
        time_diff = current_time - self.last_time
        self.last_time = current_time

        return self.get_millilitres_diff() / time_diff
