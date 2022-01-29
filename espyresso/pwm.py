#!/usr/bin/env python3
import logging

from espyresso import config

logger = logging.getLogger(__name__)


class PWM:
    def __init__(self, pigpio_pi, pwm_gpio, freq):
        logger.debug(f"PWM INIT: gpio {pwm_gpio}, freq {freq}")
        self.pigpio_pi = pigpio_pi
        self.pwm_gpio = pwm_gpio
        self.enabled = False
        self.freq = freq
        self.value = 0
        logger.debug(f"PWM READY: gpio {pwm_gpio}, freq {freq}")

    def get_display_value(self):
        return str(round(self.value * 100, 1))

    def set_value(self, value):
        if self.value != value and config.DEBUG:
            logger.debug(f"Setting PWM {self.pwm_gpio} to {value}")
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
