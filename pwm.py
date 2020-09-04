#!/usr/bin/env python3
import config


class PWM:
    def __init__(self, pigpio_pi, pwm_gpio, freq):
        self.pigpio_pi = pigpio_pi
        self.pwm_gpio = pwm_gpio
        self.enabled = False
        self.freq = freq
        self.value = 0

    def set_pwm(self, value=0):
        self.pigpio_pi.hardware_PWM(self.pwm_gpio, self.freq, value)

    def get_display_value(self):
        return str(round(self.value * 100, 1))

    def set_value(self, value):
        if self.value != value and config.DEBUG:
            print(f"Setting PWM {self.pwm_gpio} to {value}")
        self.value = value
        self.pigpio_pi.hardware_PWM(self.pwm_gpio, self.freq, int(value * (10 ** 6)))

    def enable(self):
        if not self.enabled:
            self.pigpio_pi.write(self.pwm_gpio, 1)
            self.enabled = True

    def disable(self):
        if self.enabled:
            self.pigpio_pi.write(self.pwm_gpio, 0)
            self.enabled = False
