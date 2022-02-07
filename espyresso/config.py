#!/usr/bin/env python3

DEBUG = True

if DEBUG:
    import sys

    from mock import MagicMock

    sys.modules["pigpio"] = MagicMock()

LOG_FILE = "log/espyresso.log"
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

TARGET_TEMP = 95.0
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

# characteristics of the temperature controller

BREW_SETPOINT = 95.0

ELEMENT_MAX_TEMPERATURE = 190.0
# °C the thermal fuses melt at 172°C and elements are about 20K hotter than fuse mountings

SHELL_MAX_TEMPERATURE = 152.0
# °C the temp probe circuit maxes out at about 155°C - don't exceed it or we're flying blind

AMBIENT_TEMPERATURE = 20.0
# °C this does not need to be exact

RESERVOIR_TEMPERATURE = 20.0
# °C the reservoir gets heated a little by the machine over time - model this?

LATENT_HEAT_VAPORISATION_100 = 2257.0
# J/g latent heat of vaporisation of water at 100°C

SPEC_HEAT_WATER_100 = 4.216
# J/g/K specific heat of water at 100°C

SPEC_HEAT_ALUMINIUM = 0.9
# J/g/K specific heat of aluminium (i.e. boiler shell)

SPEC_HEAT_BRASS = 0.38
# J/g/K specific heat of brass (i.e. brew head)

BOILER_VOLUME = 100.0
# ml volume of water in boiler when full (I measured it)

MASS_BOILER_SHELL = 609.0
# g mass of the aluminium boiler shell (I measured it)

MASS_BREW_HEAD = 1172.0
# g mass of the brew head (I measured it)

MASS_PORTAFILTER = 450.0
# g mass of the brew head (I measured it)

HEAT_CAPACITY_BODY = 395.0
# J/K heat capacity of the body/housing of the machine (i.e. what is lost once-off during startup)

BREWHEAD_AMBIENT_XFER_COEFF = 0.55
# W/K power lost from brew head to ambient air

BOILER_WATER_XFER_COEFF_NOFLOW = 14.7
# W/K rate at which boiler shell heats water per °C difference in boiler and water temperature

BOILER_WATER_XFER_COEFF_STEAM = 25.0
# W/K ditto for when steam is flowing

BOILER_BREWHEAD_XFER_COEFF = 3.6
# W/K ditto for the brewhead (calculated from measuring brewhead temperature at 60s of full power=14.2K+ambient and boiler temp=67.21K+ambient and rate of change of brewhead temp=0.43K/s)

ELEMENT_SHELL_XFER_COEFF = 14.0
# W/K rate at which heat transfers from element half of boiler to shell half

BOILER_BODY_XFER_COEFF = 1.8
# W/K rate at which heat transfers into the body/housing of the machine
