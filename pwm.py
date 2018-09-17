#!/usr/bin/env python3
import pigpio

class PWM():
    def __init__(self, pwm_gpio):
        self.gpio = pigpio.pi()
        self.pwm_gpio = pwm_gpio
        self.enabled = False
        pass

    def set_value(self, value):
        
        if value > 0:
            self.enable()
        else:
            self.disable()

    def enable(self):
        if not self.enabled:
            self.gpio.write(self.pwm_gpio, 1)
            self.enabled = True
        
    def disable(self):
        if self.enabled:
            self.gpio.write(self.pwm_gpio, 0)
            self.enabled = False

