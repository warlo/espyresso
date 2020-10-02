#!/usr/bin/env python3
import time

import pigpio


class Flow:
    def __init__(self, pigpio_pi=None, flow_in_gpio=None):
        self.pigpio_pi = pigpio_pi
        self.flow_in_gpio = flow_in_gpio
        self.pigpio_pi.set_mode(self.flow_in_gpio, pigpio.INPUT)
        self.callback_flow = self.pigpio_pi.callback(
            self.flow_in_gpio, pigpio.RISING_EDGE
        )

        self.flowing = False

        self.pulses_since = time.time()
        self.pulse_count = 0

    def reset_pulse_count(self):
        self.callback_flow.reset_tally()
        self.pulses_since = time.time()

    def get_pulse_count(self):
        return self.callback_flow.tally()

    def get_litres(self):
        counts_per_liter = 1925
        return self.get_pulse_count() / counts_per_liter

    def get_millilitres(self):
        return self.get_litres() * 1000

    def get_millilitres_per_sec(self):
        time_since_started = time.time() - self.pulses_since()
        return self.get_millilitres() / time_since_started
