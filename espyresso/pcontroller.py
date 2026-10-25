#!/usr/bin/env python3

import logging
import math
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from espyresso import config

if TYPE_CHECKING:
    from espyresso.flow import Flow

logger = logging.getLogger(__name__)


def boot_boost_seconds(temperature: float, setpoint: float) -> float:
    """Seconds of full power to apply after the first valid reading.

    Delivers at most BOOT_BOOST_FRACTION of the energy needed to lift water +
    shell from ``temperature`` to ``setpoint``; zero at or above setpoint."""
    if not math.isfinite(temperature):
        return 0.0
    deficit = max(0.0, setpoint - temperature)
    energy = deficit * config.BOOT_BOOST_HEAT_CAPACITY * config.BOOT_BOOST_FRACTION
    return min(config.BOOT_BOOST_MAX_SECONDS, energy / config.MAX_BOILER_POWER)


class PController:
    def __init__(self, initial_temperature: float, flow: "Flow") -> None:

        self.temp_setpoint = config.TARGET_TEMP
        self.target_offset = 0.0

        self.reset(initial_temperature)

        self.pumpPowerRate = 0.0
        self.heaterPower = 0.0
        self.lastBoilerPidTime: float = time.perf_counter()
        self.flow = flow

        self.boost_until = 0.0
        self._flow_horizon_s = 0.0
        self._flow_horizon_until = 0.0
        self._resync_error_since: Optional[float] = None
        # Populated every update() so callers can introspect intermediate
        # power terms, error, safety bounds, etc. without re-computing them.
        self.diagnostics: Dict[str, Any] = {}

    def set_target_temp(self, temperature: float) -> None:
        self.temp_setpoint = temperature

    def set_target_offset(self, offset: float) -> None:
        """Regulate to the setpoint plus ``offset`` (K), e.g. a hotter boiler
        while the group head warms (espyresso.warmup). The setpoint itself,
        which the safety limits use, is unchanged."""
        self.target_offset = offset if math.isfinite(offset) else 0.0

    @property
    def target(self) -> float:
        """What the controller regulates the modelled water to."""
        return self.temp_setpoint + self.target_offset

    def reset(self, temperature: float) -> None:
        """Initialise every thermal mass from one measurement, as at boot."""
        self.elementTemp = temperature
        self.shellTemp = temperature

        self.ambientTemp = min(self.shellTemp, config.AMBIENT_TEMPERATURE)

        self.waterTemp = temperature
        self.modeledSensorTemp = temperature

        # based on heat transfer coefficients to and from brewhead, we can caluculate its steady state temp - use that
        self.brewHeadTemp = (
            self.ambientTemp * config.BREWHEAD_AMBIENT_XFER_COEFF
            + self.shellTemp * config.BOILER_BREWHEAD_XFER_COEFF
        ) / (config.BREWHEAD_AMBIENT_XFER_COEFF + config.BOILER_BREWHEAD_XFER_COEFF)

        self.bodyTemp = self.shellTemp
        self._resync_error_since = None

    def resync(self, temperature: float) -> None:
        """Restart the boiler-side model from a measurement, as at boot.
        The brew head and body are slow and unmeasured, so they keep their
        estimates."""
        self.elementTemp = temperature
        self.shellTemp = temperature
        self.waterTemp = temperature
        self.modeledSensorTemp = temperature
        self._resync_error_since = None

    def start_boost(self, seconds: float) -> None:
        """Run the element at full power for ``seconds`` (while boiling)."""
        self.boost_until = time.perf_counter() + max(0.0, seconds)

    def set_flow_horizon(self, seconds: float) -> None:
        """Seconds of shot still to come, for a shot the Pi controls.
        Expires after FLOW_HEAT_HORIZON_EXPIRY unless refreshed."""
        self._flow_horizon_s = min(max(0.0, seconds), config.FLOW_HEAT_HORIZON_MAX)
        self._flow_horizon_until = time.perf_counter() + config.FLOW_HEAT_HORIZON_EXPIRY

    def update(
        self, *, temperature: float, boiling: bool
    ) -> Tuple[float, Tuple[float, ...]]:

        logger.debug("\n")
        current_time = time.perf_counter()
        logger.debug("CURRENT_TIME: %s", current_time)
        deltaTime = current_time - self.lastBoilerPidTime
        logger.debug("deltaTime: %s", deltaTime)
        self.lastBoilerPidTime = current_time
        logger.debug("lastBoilerPidTime: %s", self.lastBoilerPidTime)

        if not math.isfinite(temperature):
            # No usable measurement: heater off, model untouched.
            self.heaterPower = 0.0
            return 0, (
                self.shellTemp,
                self.elementTemp,
                self.waterTemp,
                self.bodyTemp,
                self.brewHeadTemp,
                self.modeledSensorTemp,
                temperature,
            )

        resync_reason = ""
        if deltaTime > config.MPC_MAX_DT:
            # Integrating a long step diverges; restart from the measurement.
            self.resync(temperature)
            deltaTime = 0.0
            resync_reason = "gap"

        flow_rate = self.flow.get_flow_rate() or 0
        logger.debug("FLOWRATE %s", flow_rate)

        # TODO: verify flow
        waterToFlowPower = (
            flow_rate
            * (self.waterTemp - config.RESERVOIR_TEMPERATURE)
            * config.SPEC_HEAT_WATER_100
        )
        logger.debug("waterToFlowPower: %s", waterToFlowPower)

        # How much power is lost to the atmosphere from the brew head?
        brewHeadToAmbientPower = (
            self.brewHeadTemp - self.ambientTemp
        ) * config.BREWHEAD_AMBIENT_XFER_COEFF
        logger.debug("brewHeadToAmbientPower: %s", brewHeadToAmbientPower)

        # How much power is transferred from the boiler to the water?
        shellToWaterPower = (
            (self.shellTemp - self.waterTemp)
            * config.BOILER_WATER_XFER_COEFF_NOFLOW
            / 2.0
        )
        logger.debug("shellToWaterPower: %s", shellToWaterPower)
        elementToWaterPower = (
            (self.elementTemp - self.waterTemp)
            * config.BOILER_WATER_XFER_COEFF_NOFLOW
            / 2.0
        )
        logger.debug("elementToWaterPower: %s", elementToWaterPower)

        # How much power is transferred from the boiler to the brew head?
        shellToBrewHeadPower = (
            (self.shellTemp - self.brewHeadTemp)
            * config.BOILER_BREWHEAD_XFER_COEFF
            / 2.0
        )
        logger.debug("shellToBrewHeadPower: %s", shellToBrewHeadPower)
        elementToBrewHeadPower = (
            (self.elementTemp - self.brewHeadTemp)
            * config.BOILER_BREWHEAD_XFER_COEFF
            / 2.0
        )
        logger.debug("elementToBrewHeadPower: %s", elementToBrewHeadPower)
        # TODO: FLOW POWER?
        waterFlowToBrewHeadPower = (
            (self.waterTemp - self.brewHeadTemp)
            * flow_rate
            * config.SPEC_HEAT_WATER_100
        )
        logger.debug("waterFlowToBrewHeadPower: %s", waterFlowToBrewHeadPower)
        elementToShellPower = (
            self.elementTemp - self.shellTemp
        ) * config.ELEMENT_SHELL_XFER_COEFF
        logger.debug("elementToShellPower: %s", elementToShellPower)
        shellToBodyPower = (
            (self.shellTemp - self.bodyTemp) * config.BOILER_BODY_XFER_COEFF / 2.0
        )
        logger.debug("shellToBodyPower: %s", shellToBodyPower)
        elementToBodyPower = (
            (self.elementTemp - self.bodyTemp) * config.BOILER_BODY_XFER_COEFF / 2.0
        )
        logger.debug("elementToBodyPower: %s", elementToBodyPower)

        # Now work out the temperature, which comes from power that didn't go into heat loss or heating the incoming water.
        logger.debug("\nTEMP:")
        self.brewHeadTemp += (
            deltaTime
            * (
                shellToBrewHeadPower
                + elementToBrewHeadPower
                + waterFlowToBrewHeadPower
                - brewHeadToAmbientPower
            )
            / (
                config.SPEC_HEAT_BRASS
                * (config.MASS_BREW_HEAD + config.MASS_PORTAFILTER)
            )
        )
        logger.debug("brewHeadTemp: %s", self.brewHeadTemp)
        self.waterTemp += (
            deltaTime
            * (shellToWaterPower + elementToWaterPower - waterToFlowPower)
            / (config.SPEC_HEAT_WATER_100 * config.BOILER_VOLUME)
        )
        logger.debug("waterTemp: %s", self.waterTemp)
        self.shellTemp += (
            deltaTime
            * (
                elementToShellPower
                - shellToBrewHeadPower
                - shellToWaterPower
                - shellToBodyPower
            )
            / (config.SPEC_HEAT_ALUMINIUM * config.MASS_BOILER_SHELL / 2.0)
        )
        logger.debug("shellTemp: %s", self.shellTemp)
        elementTempDelta = (
            deltaTime
            * (
                self.heaterPower
                - elementToShellPower
                - elementToBrewHeadPower
                - elementToWaterPower
                - elementToBodyPower
            )
            / (config.SPEC_HEAT_ALUMINIUM * config.MASS_BOILER_SHELL / 2.0)
        )
        self.elementTemp += elementTempDelta
        logger.debug("elementTemp: %s", self.elementTemp)
        self.bodyTemp += (
            deltaTime
            * (shellToBodyPower + elementToBodyPower)
            / config.HEAT_CAPACITY_BODY
        )
        logger.debug("bodyTemp: %s", self.bodyTemp)

        self.modeledSensorTemp += (
            deltaTime
            * ((self.elementTemp - self.modeledSensorTemp) * config.SENSOR_XFER_COEFF)
            / config.SENSOR_HEAT_CAPACITY
        )

        logger.debug("modeledSensorTemp: %s,%s", self.modeledSensorTemp, temperature)

        # Any delta between modeledSensorTemp and temperature is either model error diverging slowly or (fast) noise.
        # Slowly correct towards this temperature and noise will average out.
        delta_to_apply = (temperature - self.modeledSensorTemp) * (
            deltaTime * config.MPC_SMOOTHING
        )
        logger.debug("diff: %s", temperature - self.modeledSensorTemp)
        logger.debug("diffelement: %s", self.elementTemp - self.modeledSensorTemp)

        # Add delta to all thermal masses
        self.modeledSensorTemp += delta_to_apply
        self.elementTemp += delta_to_apply

        # only correct other masses when close to steady state otherwise it can diverge
        # wildly due to modelling errors
        steadystate = (
            abs(self.waterTemp - self.target) < config.MPC_STEADY_BAND
            and abs(elementTempDelta + delta_to_apply)
            < deltaTime * config.MPC_STEADY_STATE
        )
        logger.debug("steadystate %s", steadystate)
        if steadystate:
            self.shellTemp += delta_to_apply
            self.waterTemp += delta_to_apply
            self.bodyTemp += delta_to_apply
            self.brewHeadTemp += delta_to_apply

        # self.shellTemp = temperature

        if abs(temperature - self.modeledSensorTemp) > config.MPC_RESYNC_ERROR:
            if self._resync_error_since is None:
                self._resync_error_since = current_time
            elif current_time - self._resync_error_since >= config.MPC_RESYNC_SECONDS:
                self.resync(temperature)
                resync_reason = "error"
        else:
            self._resync_error_since = None

        self.diagnostics = {
            "deltaTime": deltaTime,
            "flow_rate": flow_rate,
            "waterToFlowPower": waterToFlowPower,
            "brewHeadToAmbientPower": brewHeadToAmbientPower,
            "shellToWaterPower": shellToWaterPower,
            "elementToWaterPower": elementToWaterPower,
            "shellToBrewHeadPower": shellToBrewHeadPower,
            "elementToBrewHeadPower": elementToBrewHeadPower,
            "waterFlowToBrewHeadPower": waterFlowToBrewHeadPower,
            "elementToShellPower": elementToShellPower,
            "shellToBodyPower": shellToBodyPower,
            "elementToBodyPower": elementToBodyPower,
            "elementTempDelta": elementTempDelta,
            "delta_to_apply": delta_to_apply,
            "steadystate": steadystate,
            "ambientTemp": self.ambientTemp,
            "desiredWaterInputPower": math.nan,
            "desiredAverageShellTemp": math.nan,
            "maxStableAverageShellTemp": math.nan,
            "error": math.nan,
            "heaterPower_W": 0.0,
            "maxAllowableElementToShellPower": math.nan,
            "maxAllowableElementTemp": math.nan,
            "maxAllowablePowerForElement": math.nan,
            "resync": resync_reason,
            "boost": False,
            "flow_horizon_s": 0.0,
            "target_offset": self.target_offset,
        }

        if not boiling:
            # The element is off; don't let the model keep integrating the
            # last commanded power.
            self.heaterPower = 0.0
            return 0, (
                self.shellTemp,
                self.elementTemp,
                self.waterTemp,
                self.bodyTemp,
                self.brewHeadTemp,
                self.modeledSensorTemp,
                temperature,
            )

        # arrange heater power so that the average boiler energy will be correct in 2 seconds (if possible)
        # the error term handles boiler shell and water - other known power sinks are added explicitly

        # we want the water to reach target temperature in the next 15s so calculate the necessary average temperature of the shell
        desiredWaterInputPower = (
            (self.target - self.waterTemp)
            * config.SPEC_HEAT_WATER_100
            * config.BOILER_VOLUME
            / 15.0
        )
        desiredWaterInputPower += waterToFlowPower
        logger.debug("desiredWaterInputPower: %s", desiredWaterInputPower)

        desiredAverageShellTemp = (
            self.waterTemp
            + desiredWaterInputPower / config.BOILER_WATER_XFER_COEFF_NOFLOW
        )
        logger.debug("desiredAverageShellTemp: %s", desiredAverageShellTemp)

        # now clip the temperature so that it won't take more than 20s to lose excess heat to ambient
        flow_horizon = (
            self._flow_horizon_s if current_time < self._flow_horizon_until else 0.0
        )
        maxStableAverageShellTemp = (
            (
                brewHeadToAmbientPower * 20.0
                + waterToFlowPower * flow_horizon
                - (self.waterTemp - self.target)
                * config.SPEC_HEAT_WATER_100
                * config.BOILER_VOLUME
            )
            / config.SPEC_HEAT_ALUMINIUM
            / config.MASS_BOILER_SHELL
            + self.target
        )
        logger.debug("maxStableAverageShellTemp: %s", maxStableAverageShellTemp)
        desiredAverageShellTemp = min(
            desiredAverageShellTemp, maxStableAverageShellTemp
        )
        logger.debug("desiredAverageShellTemp: %s", desiredAverageShellTemp)

        error = (
            (self.shellTemp - desiredAverageShellTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 2.0
        )
        logger.debug("error shellTemp: %s", error)
        error += (
            (self.elementTemp - desiredAverageShellTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 2.0
        )
        logger.debug("error total (shellTemp + elementTemp): %s", error)

        self.heaterPower = (
            shellToBrewHeadPower
            + elementToBrewHeadPower
            + shellToBodyPower
            + elementToBodyPower
            + shellToWaterPower
            + elementToWaterPower
            - (error / 2.0)
        )
        logger.debug("ISH LOST %s W", (self.heaterPower + (error * 2.0)))
        # keep power level safe and sane (where it would take two seconds to get triac or elements over max temp and five seconds to get shell over max temp)
        maxAllowableElementToShellPower = (
            (config.SHELL_MAX_TEMPERATURE - self.shellTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 5.0
            + shellToWaterPower
            + shellToBrewHeadPower
            + shellToBodyPower
        )
        logger.debug("maxAllowableElementToShellPower %s", maxAllowableElementToShellPower)
        maxAllowableElementTemp = (
            maxAllowableElementToShellPower / config.ELEMENT_SHELL_XFER_COEFF
            + self.shellTemp
        )
        logger.debug("maxAllowableElementTemp %s", maxAllowableElementTemp)
        maxAllowableElementTemp = min(
            maxAllowableElementTemp, config.ELEMENT_MAX_TEMPERATURE
        )
        logger.debug("maxAllowableElementTemp %s", maxAllowableElementTemp)
        maxAllowablePowerForElement = (
            (maxAllowableElementTemp - self.elementTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 2.0
            + elementToShellPower
            + elementToWaterPower
            + elementToBrewHeadPower
            + elementToBodyPower
        )
        logger.debug("maxAllowablePowerForElement %s", maxAllowablePowerForElement)

        logger.debug("heaterPower0 %s", self.heaterPower)
        self.heaterPower = min(config.MAX_BOILER_POWER, self.heaterPower)
        logger.debug("heaterPower1 %s", self.heaterPower)
        self.heaterPower = min(maxAllowablePowerForElement, self.heaterPower)
        logger.debug("heaterPower2 %s", self.heaterPower)
        self.heaterPower = max(0.0, self.heaterPower)
        logger.debug("heaterPower3 %s", self.heaterPower)
        normalizedHeaterPower = self.heaterPower / config.MAX_BOILER_POWER
        normalizedHeaterPower = max(normalizedHeaterPower, 0.0)
        normalizedHeaterPower = min(normalizedHeaterPower, 1.0)
        if not math.isfinite(normalizedHeaterPower):
            # min()/max() pass NaN through unchanged.
            normalizedHeaterPower = 0.0
            self.heaterPower = 0.0
        boosting = current_time < self.boost_until
        if boosting:
            # Tell the model: the next step integrates full power.
            normalizedHeaterPower = 1.0
            self.heaterPower = config.MAX_BOILER_POWER
        logger.debug("heaterPower normalized %s", normalizedHeaterPower)

        self.diagnostics.update(
            {
                "desiredWaterInputPower": desiredWaterInputPower,
                "desiredAverageShellTemp": desiredAverageShellTemp,
                "maxStableAverageShellTemp": maxStableAverageShellTemp,
                "error": error,
                "heaterPower_W": self.heaterPower,
                "maxAllowableElementToShellPower": maxAllowableElementToShellPower,
                "maxAllowableElementTemp": maxAllowableElementTemp,
                "maxAllowablePowerForElement": maxAllowablePowerForElement,
                "boost": boosting,
                "flow_horizon_s": flow_horizon,
            }
        )

        return min(normalizedHeaterPower, 1.0), (
            self.shellTemp,
            self.elementTemp,
            self.waterTemp,
            self.bodyTemp,
            self.brewHeadTemp,
            self.modeledSensorTemp,
            temperature,
        )
