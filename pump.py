#!/usr/bin/env python3
import pigpio
import time
import threading
from pwm import PWM


class Pump:
    def __init__(
        self,
        pigpio_pi=None,
        pump_out_gpio=None,
        pump_pwm_gpio=None,
        reset_started_time=None,
        pumping=False,
    ):
        self.pigpio_pi = pigpio_pi
        self.pump_out_gpio = pump_out_gpio
        self.pigpio_pi.set_mode(self.pump_out_gpio, pigpio.OUTPUT)

        self.pwm = PWM(pigpio_pi, pump_pwm_gpio, 1000)
        self.pumping = pumping
        self.reset_started_time = reset_started_time

        self.pwm.set_value(1)
        self.brew_thread = threading.Thread(target=self.brew_shot_routine)

    def toggle_pump(self):
        self.pumping = not self.pumping
        if not self.pumping:
            self.pigpio_pi.write(self.pump_out_gpio, 0)
        else:
            self.reset_started_time()
            self.pigpio_pi.write(self.pump_out_gpio, 1)

    def stop_pump(self):
        self.pigpio_pi.write(self.pump_out_gpio, 0)
        self.pumping = False

    def brew_shot(self):
        if self.brew_thread.is_alive():
            self.stop_pump()
        else:
            self.brew_thread.start()

    def brew_shot_routine(self):
        if self.pumping:
            self.toggle_pump()
            self.set_pwm_value(1)
            return

        started = time.time()
        self.set_pwm_value(0.5)

        self.toggle_pump()
        while self.pumping and (time.time() - started) < 5:
            time_passed = time.time() - started
            self.set_pwm_value(0.5 + 0.5 * time_passed)
            time.sleep(0.1)

        while self.pumping and (time.time() - started) < 25:
            time.sleep(0.1)

        if self.pumping:
            self.toggle_pump()

    def set_pwm_value(self, value):
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
