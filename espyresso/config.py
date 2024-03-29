#!/usr/bin/env python3
from sys import platform

# DEBUG if Mac
PLATFORM = platform
DEBUG = PLATFORM == "darwin"

if DEBUG:
    import sys

    from mock import MagicMock

    sys.modules["pigpio"] = MagicMock()

LOG_FILE = "log/espyresso.log"
LOG_POWER = False
LOG_POWER_FILE = "log/power.log"
SHOT_STAT_FILE = "shot_stat.txt"

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
TARGET_STEAM_TEMP = 135.0
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
TEMP_Y_MIN = 70
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

FLOW_METER_DEBOUNCE_TIME = 0.02
# any state change within 20ms of the last is considered a bounce error (from pump vibration)

# characteristics of the temperature controller

MAX_BOILER_POWER = 1350.0
# W the boiler can use

BREW_SETPOINT = TARGET_TEMP

ELEMENT_MAX_TEMPERATURE = 190.0
# °C the thermal fuses melt at 172°C and elements are about 20K hotter than fuse mountings

SHELL_MAX_TEMPERATURE = 152.0
# °C the temp probe circuit maxes out at about 155°C - don't exceed it or we're flying blind

AMBIENT_TEMPERATURE = 22.0
# °C this does not need to be exact

RESERVOIR_TEMPERATURE = 22.0
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

# SENSOR
# 28.847093307278953,4438.529525412,1
# 47.0200293111871,4448.538837909 - 4438.529525412

AMBIENT_FOR_CALIBRATION = 22.300928187591595
TEMPERATURE_AT_T10 = 28.847093307278953
TEMPERATURE_AT_T20 = 47.020029311187
D10 = 10.009312496999883
HEATING_RATE = (TEMPERATURE_AT_T20 - TEMPERATURE_AT_T10) / D10

SENSOR_HEAT_CAPACITY = (
    MAX_BOILER_POWER / HEATING_RATE / 1000.0
)  # exact value doesn't matter

SENSOR_XFER_COEFF = (
    SENSOR_HEAT_CAPACITY
    * HEATING_RATE
    / (D10 * HEATING_RATE - (TEMPERATURE_AT_T10 - AMBIENT_FOR_CALIBRATION))
)

MPC_STEADY_STATE = 0.5
MPC_SMOOTHING = 0.5

"""
# Calculate best SENSOR_XFER_COEFF

if self.prev_temp:
    best_coef = (
        (temperature - self.prev_temp)
        * config.SENSOR_HEAT_CAPACITY
        / (deltaTime * (self.elementTemp - self.prev_temp))
    )

    self.coef.append(best_coef)
    print("BEST_SENSOR_XFER_COEFF", best_coef, config.SENSOR_XFER_COEFF)
    print("AVG", sum(self.coef) / len(self.coef))
    logger.warning(
        "BEST_SENSOR_XFER_COEFF: %s (now: %s)",
        best_coef,
        config.SENSOR_XFER_COEFF,
    )
    logger.warning("AVG %s", sum(self.coef) / len(self.coef))

self.prev_temp = temperature
"""
# SENSOR_XFER_COEFF = 0.017899826668980535
# SENSOR_XFER_COEFF = 0.0340
SENSOR_XFER_COEFF = 0.02656

# BLUETOOTH SCALE
BLUETOOTH_NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
BLUETOOTH_SCALE_ADDRESS = (
    "08D33DC9-564F-83B6-9788-DD1E1F6672A2"
    if platform == "darwin"
    else "B8:CA:04:28:79:84"
)
