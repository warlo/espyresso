#!/usr/bin/env python3
import pigpio
import time


class Flow:
    def __init__(self, pigpio_pi=None, flow_in_gpio=None):
        self.pigpio_pi = pigpio_pi
        self.flow_in_gpio = flow_in_gpio
        self.pigpio_pi.set_mode(self.flow_in_gpio, pigpio.INPUT)
        self.callback_flow = self.pigpio_pi.callback(
            self.flow_in_gpio, pigpio.RISING_EDGE, self.flow_pulse_callback
        )

        self.flowing = False

        self.pulses_since = time.time()
        self.pulse_count = 0

    def flow_pulse_callback(self):

        if self.pulse_count == 0:
            self.flowing = True
            self.pulses_since = time.time()
        if (time.time() - self.pulses_since) > 0.250:
            pass
            # self.flowing = False

        if self.flowing:
            self.increment_pulse_count()
        print("PULSE", self.pulse_count)

    def reset_pulse_count(self):
        self.pulse_count = 0

    def increment_pulse_count(self):
        self.pulse_count += 1

    def get_pulse_count(self):
        return self.pulse_count

    def get_litres(self):
        counts_per_liter = 4095
        return self.get_pulse_count() / counts_per_liter
