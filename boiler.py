#!/usr/bin/env python3
import config
from pwm import PWM


class Boiler:
    def __init__(
        self,
        pigpio_pi=None,
        pwm_gpio=None,
        reset_started_time=None,
        boiling=True,
        add_to_queue=None,
    ):
        self.pwm = PWM(pigpio_pi, pwm_gpio, 2)
        self.boiling = boiling
        self.reset_started_time = reset_started_time

        self.pwm_override = None
        self.set_pwm_override(None)
        self.add_to_queue = add_to_queue

        if self.boiling and not config.DEBUG:
            # Start boiling initially
            self.pwm.set_value(1.0)

    def get_boiling(self):
        return self.boiling

    def toggle_boiler(self):
        self.boiling = not self.get_boiling()
        if not self.boiling:
            self.pwm.set_value(0)
        else:
            self.reset_started_time()

    def set_pwm_override(self, value):
        self.pwm_override = value

        if self.pwm_override:
            self.pwm.set_value(self.pwm_override)
        else:
            self.pwm.set_value(0)

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
        self.add_to_queue(self.pwm.get_display_value())
