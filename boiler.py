#!/usr/bin/env python3
from pwm import PWM


class Boiler:
    def __init__(self, pi, pwm_gpio):
        self.pwm = PWM(pi, pwm_gpio)

    def set_value(self, value):
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
