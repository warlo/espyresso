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

        self.active = False

    def turn_off_system(self):
        print('asd')
        os.system("shutdown now -h")

    def toggle_boiler(self):
        self.boiler.toggle_boiler()

    def callback_button_one(self, gpio, level, tick):

        self.active = True
        seconds = 0
        self.boiler.toggle_boiler()
        while self.active:
            print('seconds', seconds)
            time.sleep(1)
            seconds += 1
            if seconds > 5:
                self.turn_off_system()
    
    def reset_button_one(self, gpio, level, tick):
        print('RESETTING')
        self.active = False


