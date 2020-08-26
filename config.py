#!/usr/bin/env python3

DEBUG = True

TSIC_GPIO = 24
BOILER_PWM_GPIO = 12

PUMP_OUT_GPIO = 23
PUMP_PWM_GPIO = 19

BREW_IN_GPIO = 14
FLOW_IN_GPIO = 5

RANGER_ECHO_IN = 27
RANGER_TRIGGER_OUT = 4

BUTTON_ONE_GPIO = 21
BUTTON_TWO_GPIO = 20

SDA_GPIO = 2
SCL_GPIO = 3

TARGET_TEMP = 94.0
KP = 0.075
KI = 0.0608
KD = 0.90
IMIN = 0.0
IMAX = 1.0

TURN_OFF_SECONDS = 600.0
