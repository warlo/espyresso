#!/usr/bin/env python3
from pwm import PWM


class Boiler:
    def __init__(self, pi, pwm_gpio, reset_started_time, boiling=True):
        self.pwm = PWM(pi, pwm_gpio)
        self.boiling = boiling
        self.reset_started_time = reset_started_time
        if self.boiling:
            # Start boiling initially
            self.pwm.set_value(1.0)

    def toggle_boiler(self):
        self.boiling = not self.boiling
        if not self.boiling:
            self.pwm.set_value(0)
        else:
            self.reset_started_time()

    def set_value(self, value):
        if not self.boiling:
            return

        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
