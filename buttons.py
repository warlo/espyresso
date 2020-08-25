#!/usr/bin/env python3
import os
import time

import pigpio


class Buttons:
    def __init__(
        self,
        *,
        pigpio_pi=None,
        boiler=None,
        pump=None,
        display=None,
        button_one=None,
        button_two=None
    ):
        self.pigpio_pi = pigpio_pi
        self.button_one = button_one
        self.button_two = button_two
        self.boiler = boiler
        self.pump = pump
        self.display = display

        self.pigpio_pi.set_mode(self.button_one, pigpio.INPUT)
        self.pigpio_pi.set_mode(self.button_two, pigpio.INPUT)
        self.pigpio_pi.set_pull_up_down(self.button_one, pigpio.PUD_DOWN)
        self.pigpio_pi.set_pull_up_down(self.button_two, pigpio.PUD_DOWN)

        self.callback_one = self.pigpio_pi.callback(
            self.button_one, pigpio.RISING_EDGE, self.callback_button_one
        )
        self.callback_two = self.pigpio_pi.callback(
            self.button_two, pigpio.RISING_EDGE, self.callback_button_two
        )

    def turn_off_system(self):
        os.system("shutdown now -h")

    def callback_button_one(self, gpio, level, tick):
        timestamp = time.time()
        while True:
            seconds = time.time() - timestamp
            if not self.pigpio_pi.read(self.button_one):
                if seconds > 0.25:
                    self.pump.brew_shot()
                return
            time.sleep(0.2)

    def callback_button_two(self, gpio, level, tick):
        timestamp = time.time()
        while True:
            seconds = time.time() - timestamp
            self.display.notification = str(int(seconds) + 1)
            if seconds >= 2:
                self.turn_off_system()
            elif not self.pigpio_pi.read(self.button_one):
                if seconds > 0.25 and seconds < 2:
                    self.boiler.toggle_boiler()
                self.display.notification = ""
                return
            time.sleep(0.2)

    def reset_button_one(self, gpio, level, tick):
        pass
