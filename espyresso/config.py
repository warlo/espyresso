#!/usr/bin/env python3

DEBUG = True

if DEBUG:
    import sys

    from mock import MagicMock

    sys.modules["pigpio"] = MagicMock()

LOG_FILE = "espyresso.log"
SHOT_COUNT_FILE = "shot_count.txt"

TSIC_GPIO = 24
BOILER_PWM_GPIO = 12

PUMP_OUT_GPIO = 23
PUMP_PWM_GPIO = 19

BREW_IN_GPIO = 14  # TODO: Add support for BREW IN
FLOW_IN_GPIO = 5

RANGER_ECHO_IN = 27
RANGER_TRIGGER_OUT = 4

BUTTON_ONE_GPIO = 21
BUTTON_TWO_GPIO = 20

SDA_GPIO = 2  # TODO: Add support for pressure meter
SCL_GPIO = 3

TARGET_TEMP = 94.0
KP = 0.0762
KI = 0.0616
KD = 0.905
IMIN = 0.0
IMAX = 1.0

TURN_OFF_SECONDS = 600.0

WIDTH = 320
HEIGHT = 240

AXIS_WIDTH = 28

TEMP_X_MIN = 0 + AXIS_WIDTH
TEMP_X_MAX = 160
TEMP_Y_MIN = 50
TEMP_Y_MAX = 240

FLOW_X_MIN = 160 + AXIS_WIDTH
FLOW_X_MAX = 320
FLOW_Y_MIN = 50
FLOW_Y_MAX = 140

BOILER_X_MIN = 160 + AXIS_WIDTH
BOILER_X_MAX = 320
BOILER_Y_MIN = 150
BOILER_Y_MAX = 240

ZOOM = 2
