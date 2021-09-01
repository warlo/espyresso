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
        brewing_timer=None,
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
        self.brewing_timer = brewing_timer

        self.started_preinfuse = None
        self.stopped_preinfuse = None

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

    def get_time_since_started_preinfuse(self):
        if self.stopped_preinfuse and self.started_preinfuse:
            return self.stopped_preinfuse - self.started_preinfuse
        if self.started_preinfuse and self.pumping:
            return time.time() - self.started_preinfuse
        return 0

    def brew_shot(self):
        if self.brew_thread.is_alive():
            self.brewing_timer.stop_timer()
            self.stop_pump()
        else:
            self.brew_thread = threading.Thread(target=self.brew_shot_routine)
            self.reset_started_time()
            self.brew_thread.start()

    def brew_shot_routine(self):
        # If already pumping then reset the routing
        if self.pumping:
            return self.reset_routine()

        # Reset flow meter
        self.flow.reset_pulse_count()

        # Hard-code boiler to 30% during preinfuse and start pump at 0.5 PWM (2-3 bars?)
        self.set_pwm_value(0.5)
        self.boiler.set_pwm_override(0.30)
        self.toggle_pump()

        # Set started preinfuse time
        self.started_preinfuse = time.time()
        self.stopped_preinfuse = None

        # Sleep until flow is above 30ml or 7seconds
        while self.pumping and not (
            self.flow.get_millilitres() > 30
            or (time.time() - self.started_preinfuse) > 7
        ):
            time.sleep(0.1)

        # Stop preinfuse timer
        self.stopped_preinfuse = time.time()

        # Start brewing timer
        self.brewing_timer.reset_timer()
        self.brewing_timer.start_timer()

        # Hard-code boiler to 27.5%
        self.boiler.set_pwm_override(0.275)

        while self.pumping and self.flow.get_millilitres() < (30 + 36):
            time_passed = self.brewing_timer.get_time_since_started()

            # Gradually increase pump PWM to 100% over 5sec
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
        self.brewing_timer.stop_timer()
        if not self.stopped_preinfuse:
            self.stopped_preinfuse = time.time()

    def set_pwm_value(self, value):
        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
