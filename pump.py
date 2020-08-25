#!/usr/bin/env python3
import time
from pwm import PWM


class Pump:
    def __init__(
        self, pigpio_pi=None, pump_pwm_gpio=None, reset_started_time=None, pumping=False
    ):
        self.pwm = PWM(pigpio_pi, pump_pwm_gpio, 1000)
        self.pumping = pumping
        self.reset_started_time = reset_started_time

        self.pwm.set_value(0)

    def toggle_pump(self):
        self.pumping = not self.pumping
        if not self.pumping:
            self.pwm.set_value(0)
        else:
            self.reset_started_time()

    def brew_shot(self):
        if self.pumping:
            return

        started = time.time()
        self.set_pwm_value(0.5)

        self.toggle_pump()
        for i in range(50, 100):
            self.set_pwm_value(i/100)
            time.sleep(0.1)
        
        while (started - time.time()) < 25:
            time.sleep(0.1)
        
        if self.pumping:
            self.toggle_pump()

    def set_pwm_value(self, value):
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
