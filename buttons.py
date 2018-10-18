#!/usr/bin/env python3
import os, pigpio, time

class Buttons:
    def __init__(self, gpio, boiler, display, button_one, button_two):
        self.gpio = gpio
        self.button_one = button_one
        self.button_two = button_two
        self.boiler = boiler
        self.display = display

        self.gpio.set_mode(self.button_one, pigpio.INPUT)
        self.gpio.set_mode(self.button_two, pigpio.INPUT)
        self.gpio.set_pull_up_down(self.button_one, pigpio.PUD_DOWN)
        self.gpio.set_pull_up_down(self.button_two, pigpio.PUD_DOWN)

        self.callback_one = self.gpio.callback(self.button_one, pigpio.RISING_EDGE, self.callback_button_one)

    def turn_off_system(self):
        os.system("shutdown now -h")

    def callback_button_one(self, gpio, level, tick):
        seconds = 0
        while True:
            seconds += 0.01
            if int(seconds) % 1 == 0:
                self.display.notification = str(seconds)
            if seconds > 5:
                self.turn_off_system()
            if not self.gpio.read(self.button_one):
                if seconds > 0.01 and seconds < 5:
                    self.boiler.toggle_boiler()
                self.display.notification = ''
                return
            time.sleep(0.01)
    
    def reset_button_one(self, gpio, level, tick):
        pass


