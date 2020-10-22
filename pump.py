#!/usr/bin/env python3
import threading
import time

import pigpio

from pwm import PWM


class Pump:
    def __init__(
        self,
        pigpio_pi=None,
        boiler=None,
        flow=None,
        pump_out_gpio=None,
        pump_pwm_gpio=None,
        reset_started_time=None,
        pumping=False,
    ):
        self.pigpio_pi = pigpio_pi
        self.boiler = boiler
        self.flow = flow
        self.pump_out_gpio = pump_out_gpio
        self.pigpio_pi.set_mode(self.pump_out_gpio, pigpio.OUTPUT)

        self.pwm = PWM(pigpio_pi, pump_pwm_gpio, 1000)
        self.pumping = pumping
        self.reset_started_time = reset_started_time

        self.started_brew = None
        self.stopped_brew = None

        self.set_pwm_value(1)
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
        self.boiler.set_pwm_override(None)
        self.pumping = False

    def get_time_since_started_brew(self):
        if self.stopped_brew and self.started_brew:
            return self.stopped_brew - self.started_brew
        if self.started_brew and self.pumping:
            return time.time() - self.started_brew
        return 0

    def brew_shot(self):
        if self.brew_thread.is_alive():
            self.stopped_brew = time.time()
            self.stop_pump()
        else:
            self.brew_thread = threading.Thread(target=self.brew_shot_routine)
            self.reset_started_time()
            self.brew_thread.start()

    def brew_shot_routine(self):
        if self.pumping:
            return self.reset_routine()

        self.flow.reset_pulse_count()

        self.set_pwm_value(0.5)
        self.boiler.set_pwm_override(0.30)
        self.toggle_pump()

        started_preinfuse = time.time()
        while self.pumping and (
            self.flow.get_millilitres() < 35 or (time.time() - started_preinfuse) < 5
        ):
            time.sleep(0.1)

        self.stopped_brew = None
        self.started_brew = time.time()
        self.boiler.set_pwm_override(0.275)
        self.flow.reset_pulse_count()

        while self.pumping and self.flow.get_millilitres() < 36:
            time_passed = time.time() - self.started_brew
            if time_passed < 5:
                self.set_pwm_value(0.5 + 0.5 * (time_passed / 5))
            if time_passed > 45:
                return self.reset_routine()

            time.sleep(0.05)

        return self.reset_routine()

    def reset_routine(self):
        if self.pumping:
            self.toggle_pump()
        self.set_pwm_value(1)
        self.boiler.set_pwm_override(None)
        self.stopped_brew = time.time()

    def set_pwm_value(self, value):
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
