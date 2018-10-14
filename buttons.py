#!/usr/bin/env python3
import os, pigpio, time

class Buttons:
    def __init__(self, gpio, boiler, button_one, button_two):
        self.gpio = gpio
        self.button_one = button_one
        self.button_two = button_two
        self.boiler = boiler

        self.gpio.set_mode(self.button_one, pigpio.INPUT)
        self.gpio.set_mode(self.button_two, pigpio.INPUT)
        self.gpio.set_pull_up_down(self.button_one, pigpio.PUD_DOWN)
        self.gpio.set_pull_up_down(self.button_two, pigpio.PUD_DOWN)

        self.callback_one = self.gpio.callback(self.button_one, pigpio.RISING_EDGE, self.callback_button_one)
        self.reset_one = self.gpio.callback(self.button_one, pigpio.FALLING_EDGE, self.reset_button_one)

        self.callback_two = self.gpio.callback(self.button_two, pigpio.RISING_EDGE, self.callback_button_one)
        self.reset_two = self.gpio.callback(self.button_two, pigpio.FALLING_EDGE, self.reset_button_one)

        self.previous_tick = None
        self.time_called = None

    def turn_off_system(self):
        print('asd')
        os.system("shutdown now -h")

    def toggle_boiler(self):
        self.boiler.toggle_boiler()

    def callback_button_one(self, gpio, level, tick):
        self.time_called = time.time()
    
    def reset_button_one(self, gpio, level, tick):
        if not self.time_called:
            return
        diff = int(time.time() - self.time_called)
        print('RESETTING', diff)
        if diff < 5:
            self.toggle_boiler()
        else:
            self.turn_off_system()


