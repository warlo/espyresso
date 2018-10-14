#!/usr/bin/env python3


class PWM:
    def __init__(self, gpio, pwm_gpio):
        self.gpio = gpio
        self.pwm_gpio = pwm_gpio
        self.enabled = False

    def set_pwm(self, value=0):
        self.gpio.hardware_PWM(self.pwm_gpio, 2, value)

    def set_value(self, value):
        self.gpio.hardware_PWM(self.pwm_gpio, 2, int(value * (10 ** 6)))

    def enable(self):
        if not self.enabled:
            self.gpio.write(self.pwm_gpio, 1)
            self.enabled = True

    def disable(self):
        if self.enabled:
            self.gpio.write(self.pwm_gpio, 0)
            self.enabled = False
