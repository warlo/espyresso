#!/usr/bin/env python3
import config
import threading
from pwm import PWM


class Boiler:
    def __init__(
        self, pigpio_pi=None, pwm_gpio=None, reset_started_time=None, boiling=True
    ):
        self.pwm = PWM(pigpio_pi, pwm_gpio, 2)
        self.boiling = boiling
        self.reset_started_time = reset_started_time
        self.event = threading.Event()
        self.event.set()

        self.pwm_override = None

        if self.boiling and not config.DEBUG:
            # Start boiling initially
            self.pwm.set_value(1.0)

    def get_boiling(self):
        if self.event.wait(timeout=1):
            return self.boiling
        return False

    def toggle_boiler(self):
        boiling = self.get_boiling()
        self.event.clear()
        self.boiling = not boiling
        self.event.set()
        if not self.boiling:
            self.pwm.set_value(0)
        else:
            self.reset_started_time()

    def set_pwm_override(self, value):
        self.pwm_override = value

        if self.pwm_override:
            self.pwm.set_value(self.pwm_override)

    def set_value(self, value):
        if not self.get_boiling():
            return

        if self.pwm_override:
            return

        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
