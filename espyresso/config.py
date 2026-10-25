#!/usr/bin/env python3
from sys import platform

# DEBUG if Mac
PLATFORM = platform
DEBUG = PLATFORM == "darwin"

if DEBUG:
    import sys

    from unittest.mock import MagicMock

    sys.modules["pigpio"] = MagicMock()

LOG_FILE = "log/espyresso.log"
LOG_POWER = False
LOG_POWER_FILE = "log/power.log"
SHOT_STAT_FILE = "shot_stat.txt"

# Structured CSV logging of every controller tick + lifecycle events.
# Writes log/shot-<ts>-tick.csv and log/shot-<ts>-event.csv.
LOG_SHOT = True
LOG_SHOT_DIR = "log"

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

# Brew temperature. The controller regulates the boiler water; the water that
# reaches the coffee has lost heat to the group on the way. BREW_PUCK_TEMP is
# what you want at the puck (Tim Wendelboe-style light roasts: 93-94 C) and
# PUCK_OFFSET how much hotter the boiler must be to deliver it. The offset is a
# simulation estimate (tools/sim/report.py setpoints, central case): measure the
# puck temperature once and correct it here.
BREW_PUCK_TEMP = 93.0
PUCK_OFFSET = 6.0
TARGET_TEMP = BREW_PUCK_TEMP + PUCK_OFFSET
TARGET_STEAM_TEMP = 135.0
KP = 0.0762
KI = 0.0616
KD = 0.905
IMIN = 0.0
IMAX = 1.0

# Brew routine (Pi button shots). Tim Wendelboe's espresso: 19-20 g in,
# 42-45 g out, 25-35 s. Without a scale the shot stops on inlet volume from the
# flow meter: yield + water retained by the puck and basket. The retention is
# an estimate: weigh a few shots and adjust (tools/sim/README.md).
BREW_DOSE_G = 20.0
BREW_TARGET_YIELD_G = 44.0
BREW_RETAINED_ML_PER_G = 1.25
BREW_MAX_SECONDS = 45.0
# Preinfusion at low pump power until this volume or time, whichever first.
# At ~1.4 mL/s every logged shot hit the 7 s limit first.
PREINFUSE_MAX_SECONDS = 7.0
PREINFUSE_TARGET_ML = 30.0
# Steam mode (long press on button one): hold TARGET_STEAM_TEMP for up to
# STEAM_SECONDS. STEAM_REFILL_PWM > 0 pulses the pump (0.5 s on / 0.5 s off)
# to refill the boiler while steaming. Off by default: a 2 min session only
# boils off ~25-35 g of the ~120 mL boiler, and in simulation a refill of
# ~1 mL/s kept the water around 110 C while the element side ran into the
# 145 C safety cap (the refill flow at this PWM was never measured).
STEAM_SECONDS = 120.0
STEAM_REFILL_PWM = 0.0
# Brew head counts as warm once the model says it is within this of the
# setpoint (was a fixed 80 C, which only fit a 95 C setpoint).
BREWHEAD_READY_BELOW_SETPOINT = 15.0

# Boiler auto-off after this long without a Pi button action or water flow.
TURN_OFF_SECONDS = 1800.0
# Flow that postpones auto-off; smaller amounts are meter noise.
AUTO_OFF_MIN_FLOW_ML = 10.0

# Safety (espyresso/safety.py). These act on the raw sensor and the control
# heartbeat only, so they hold even when the model is wrong.
# Heater forced off when the controller hasn't completed a tick for this long
# (the longest logged gap between ticks is 0.7 s).
CONTROL_STALE_SECONDS = 2.0
WATCHDOG_INTERVAL = 0.5
# Heater cut while the raw sensor reads above setpoint + this margin, and above
# an absolute cap (TSIC 306 tops out at 150 C). Heals when it cools.
SAFETY_MAX_ABOVE_SETPOINT = 15.0
SAFETY_MAX_TEMPERATURE = 145.0
# Sensor-detached detection: near full power for this long, far below
# setpoint, no water flowing, and the sensor rose less than this. Latched
# until the boiler is switched on again.
SAFETY_RUNAWAY_SECONDS = 60.0
SAFETY_RUNAWAY_MIN_RISE = 3.0
SAFETY_RUNAWAY_BELOW_SETPOINT = 10.0
# Longest legitimate pump run is the 120 s preheat/steam routine.
PUMP_MAX_ON_SECONDS = 130.0

WIDTH = 320
HEIGHT = 240

# Display refresh rate. Kept intentionally low: the Pi Zero is CPU-bound and
# the TSIC temperature callback shares the GIL with the display thread. A
# lower FPS means the display releases the GIL more, giving the temperature
# control loop more room to run.
DISPLAY_FPS = 4

AXIS_WIDTH = 28

# Display layout (320 x 240). All rects are (x, y, w, h) in screen coords.
# Header (320x30): hero current temp + status info.
# Brew strip (320x16): brew/preinfuse/flow/scale labels.
# Temp panel (160x194): compact 6-mass legend (40px) + waveform (154px).
# Flow + Boiler panels stack on the right: each is (160x97) with a 14px
# header strip above their waveform.
LAYOUT_HEADER = (0, 0, 320, 30)
LAYOUT_BREW = (0, 30, 320, 16)
LAYOUT_TEMP_LEGEND = (0, 46, 160, 40)
LAYOUT_TEMP_WAVE = (0, 86, 160, 154)
LAYOUT_FLOW_HEADER = (160, 46, 160, 14)
LAYOUT_FLOW_WAVE = (160, 60, 160, 83)
LAYOUT_BOILER_HEADER = (160, 143, 160, 14)
LAYOUT_BOILER_WAVE = (160, 157, 160, 83)

# Waveform plot regions. X_MIN/X_MAX define the column range and therefore
# the WaveQueue length; keeping them unchanged preserves the existing
# 132-sample rolling buffer width and the test that asserts it.
TEMP_X_MIN = 0 + AXIS_WIDTH
TEMP_X_MAX = 160
TEMP_Y_MIN = 86
TEMP_Y_MAX = 240

FLOW_X_MIN = 160 + AXIS_WIDTH
FLOW_X_MAX = 320
FLOW_Y_MIN = 60
FLOW_Y_MAX = 143

BOILER_X_MIN = 160 + AXIS_WIDTH
BOILER_X_MAX = 320
BOILER_Y_MIN = 157
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

# Self-healing. Controller steps longer than this (stalled callbacks, the slow
# first step after start-up) are not integrated: the correction gain is
# dt * MPC_SMOOTHING, which overshoots for dt > 2 s and diverges for long gaps.
# The model restarts from the measurement instead.
MPC_MAX_DT = 1.0
# A model-vs-sensor error this large (K) for this long (s) means the model has
# lost track, e.g. the boiler heated while the app was down. Logged operation
# never exceeded 2.4 K, so this only fires on real faults.
MPC_RESYNC_ERROR = 5.0
MPC_RESYNC_SECONDS = 1.0
# Correct every thermal mass (not only the element) once the modelled water is
# within this band of the setpoint and settled. Relative to the setpoint so it
# works for any brew temperature and for steam.
MPC_STEADY_BAND = 1.0

# Warm-up boost: full power for a while after the first valid reading, before
# the controller's own judgement takes over. Sized to deliver at most
# BOOT_BOOST_FRACTION of the energy needed to lift water + shell (about
# BOOT_BOOST_HEAT_CAPACITY J/K) to the setpoint, so it can never overshoot by
# itself and is zero when the boiler is already hot. The model is told about
# the energy, so control stays consistent afterwards.
BOOT_BOOST_MAX_SECONDS = 6.0
BOOT_BOOST_HEAT_CAPACITY = 1200.0
BOOT_BOOST_FRACTION = 0.5

# In-shot heat budget for shots the Pi runs (it knows how much water is still
# to come). The incoming cold water is a known heat sink, so the shell may
# hold the energy it will remove over the remaining shot time, up to this many
# seconds. Must be refreshed by the brew routine; expires on its own so a dead
# pump thread cannot leave it on. Manual shots (unknown end) get none: a fixed
# horizon overheats after an unannounced stop (simulated: +2 K on a second shot).
FLOW_HEAT_HORIZON_MAX = 20.0
FLOW_HEAT_HORIZON_EXPIRY = 1.0

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
# Set False to skip the bluetooth notify loop entirely. The scale is optional;
# when disabled, get_scale_weight() returns 0 and the display loop is not
# coupled to bluetooth init at all.
BLUETOOTH_ENABLED = False
BLUETOOTH_NOTIFY_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
BLUETOOTH_SCALE_ADDRESS = (
    "08D33DC9-564F-83B6-9788-DD1E1F6672A2"
    if platform == "darwin"
    else "B8:CA:04:28:79:84"
)
