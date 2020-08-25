#!/usr/bin/env python3


class PWM:
    def __init__(self, pigpio_pi, pwm_gpio, freq):
        self.pigpio_pi = pigpio_pi
        self.pwm_gpio = pwm_gpio
        self.enabled = False
        self.freq = freq

    def set_pwm(self, value=0):
        self.pigpio_pi.hardware_PWM(self.pwm_gpio, self.freq, value)

    def set_value(self, value):
        self.pigpio_pi.hardware_PWM(self.pwm_gpio, self.freq, int(value * (10 ** 6)))

    def enable(self):
        if not self.enabled:
            self.pigpio_pi.write(self.pwm_gpio, 1)
            self.enabled = True

    def disable(self):
        if self.enabled:
            self.pigpio_pi.write(self.pwm_gpio, 0)
            self.enabled = False
