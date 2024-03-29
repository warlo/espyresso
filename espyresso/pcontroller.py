#!/usr/bin/env python3

import logging
import time
from typing import TYPE_CHECKING, Tuple

from espyresso import config

if TYPE_CHECKING:
    from espyresso.flow import Flow

logger = logging.getLogger(__name__)


class PController:
    def __init__(self, initial_temperature: float, flow: "Flow") -> None:

        self.temp_setpoint = config.TARGET_TEMP

        self.elementTemp = initial_temperature
        self.shellTemp = initial_temperature

        self.ambientTemp = min(self.shellTemp, config.AMBIENT_TEMPERATURE)

        self.waterTemp = initial_temperature
        self.modeledSensorTemp = initial_temperature

        # based on heat transfer coefficients to and from brewhead, we can caluculate its steady state temp - use that
        self.brewHeadTemp = (
            self.ambientTemp * config.BREWHEAD_AMBIENT_XFER_COEFF
            + self.shellTemp * config.BOILER_BREWHEAD_XFER_COEFF
        ) / (config.BREWHEAD_AMBIENT_XFER_COEFF + config.BOILER_BREWHEAD_XFER_COEFF)

        self.bodyTemp = self.shellTemp

        self.pumpPowerRate = 0.0
        self.heaterPower = 0.0
        self.lastBoilerPidTime: float = time.perf_counter()
        self.flow = flow

    def set_target_temp(self, temperature: float) -> None:
        self.temp_setpoint = temperature

    def update(
        self, *, temperature: float, boiling: bool
    ) -> Tuple[float, Tuple[float, ...]]:

        logger.debug("\n")
        current_time = time.perf_counter()
        logger.debug(f"CURRENT_TIME: {current_time}")
        deltaTime = current_time - self.lastBoilerPidTime
        logger.debug(f"deltaTime: {deltaTime}")
        self.lastBoilerPidTime = current_time
        logger.debug(f"lastBoilerPidTime: {self.lastBoilerPidTime}")

        flow_rate = self.flow.get_flow_rate() or 0
        logger.debug(f"FLOWRATE {flow_rate}")
        # Max flow rate
        flow_rate = flow_rate if flow_rate < 2.0 else 2.0

        # TODO: verify flow
        waterToFlowPower = (
            flow_rate
            * (self.waterTemp - config.RESERVOIR_TEMPERATURE)
            * config.SPEC_HEAT_WATER_100
        )
        logger.debug(f"waterToFlowPower: {waterToFlowPower}")

        # How much power is lost to the atmosphere from the brew head?
        brewHeadToAmbientPower = (
            self.brewHeadTemp - self.ambientTemp
        ) * config.BREWHEAD_AMBIENT_XFER_COEFF
        logger.debug(f"brewHeadToAmbientPower: {brewHeadToAmbientPower}")

        # How much power is transferred from the boiler to the water?
        shellToWaterPower = (
            (self.shellTemp - self.waterTemp)
            * config.BOILER_WATER_XFER_COEFF_NOFLOW
            / 2.0
        )
        logger.debug(f"shellToWaterPower: {shellToWaterPower}")
        elementToWaterPower = (
            (self.elementTemp - self.waterTemp)
            * config.BOILER_WATER_XFER_COEFF_NOFLOW
            / 2.0
        )
        logger.debug(f"elementToWaterPower: {elementToWaterPower}")

        # How much power is transferred from the boiler to the brew head?
        shellToBrewHeadPower = (
            (self.shellTemp - self.brewHeadTemp)
            * config.BOILER_BREWHEAD_XFER_COEFF
            / 2.0
        )
        logger.debug(f"shellToBrewHeadPower: {shellToBrewHeadPower}")
        elementToBrewHeadPower = (
            (self.elementTemp - self.brewHeadTemp)
            * config.BOILER_BREWHEAD_XFER_COEFF
            / 2.0
        )
        logger.debug(f"elementToBrewHeadPower: {elementToBrewHeadPower}")
        # TODO: FLOW POWER?
        waterFlowToBrewHeadPower = (
            (self.waterTemp - self.brewHeadTemp)
            * flow_rate
            * config.SPEC_HEAT_WATER_100
        )
        logger.debug(f"waterFlowToBrewHeadPower: {waterFlowToBrewHeadPower}")
        elementToShellPower = (
            self.elementTemp - self.shellTemp
        ) * config.ELEMENT_SHELL_XFER_COEFF
        logger.debug(f"elementToShellPower: {elementToShellPower}")
        shellToBodyPower = (
            (self.shellTemp - self.bodyTemp) * config.BOILER_BODY_XFER_COEFF / 2.0
        )
        logger.debug(f"shellToBodyPower: {shellToBodyPower}")
        elementToBodyPower = (
            (self.elementTemp - self.bodyTemp) * config.BOILER_BODY_XFER_COEFF / 2.0
        )
        logger.debug(f"elementToBodyPower: {elementToBodyPower}")

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
        logger.debug(f"brewHeadTemp: {self.brewHeadTemp}")
        self.waterTemp += (
            deltaTime
            * (shellToWaterPower + elementToWaterPower - waterToFlowPower)
            / (config.SPEC_HEAT_WATER_100 * config.BOILER_VOLUME)
        )
        logger.debug(f"waterTemp: {self.waterTemp}")
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
        logger.debug(f"shellTemp: {self.shellTemp}")
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
        logger.debug(f"elementTemp: {self.elementTemp}")
        self.bodyTemp += (
            deltaTime
            * (shellToBodyPower + elementToBodyPower)
            / config.HEAT_CAPACITY_BODY
        )
        logger.debug(f"bodyTemp: {self.bodyTemp}")

        self.modeledSensorTemp += (
            deltaTime
            * ((self.elementTemp - self.modeledSensorTemp) * config.SENSOR_XFER_COEFF)
            / config.SENSOR_HEAT_CAPACITY
        )

        logger.debug(f"modeledSensorTemp: {self.modeledSensorTemp},{temperature}")

        # Any delta between modeledSensorTemp and temperature is either model error diverging slowly or (fast) noise.
        # Slowly correct towards this temperature and noise will average out.
        delta_to_apply = (temperature - self.modeledSensorTemp) * (
            deltaTime * config.MPC_SMOOTHING
        )
        logger.debug(f"diff: {temperature - self.modeledSensorTemp}")
        logger.debug(f"diffelement: {self.elementTemp - self.modeledSensorTemp}")

        # Add delta to all thermal masses
        self.modeledSensorTemp += delta_to_apply
        self.elementTemp += delta_to_apply

        # only correct other masses when close to steady state otherwise it can diverge
        # wildly due to modelling errors
        steadystate = (
            94 < self.waterTemp < 96
            and abs(elementTempDelta + delta_to_apply)
            < deltaTime * config.MPC_STEADY_STATE
        )
        logger.debug(f"steadystate {steadystate}")
        if steadystate:
            self.shellTemp += delta_to_apply
            self.waterTemp += delta_to_apply
            self.bodyTemp += delta_to_apply
            self.brewHeadTemp += delta_to_apply

        # self.shellTemp = temperature

        if not boiling:
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
            (self.temp_setpoint - self.waterTemp)
            * config.SPEC_HEAT_WATER_100
            * config.BOILER_VOLUME
            / 15.0
        )
        desiredWaterInputPower += waterToFlowPower
        logger.debug(f"desiredWaterInputPower: {desiredWaterInputPower}")

        desiredAverageShellTemp = (
            self.waterTemp
            + desiredWaterInputPower / config.BOILER_WATER_XFER_COEFF_NOFLOW
        )
        logger.debug(f"desiredAverageShellTemp: {desiredAverageShellTemp}")

        # TODO: Flow 0
        if flow_rate > 1.0:
            desiredAverageShellTemp = self.waterTemp + desiredWaterInputPower / 25.0

        # now clip the temperature so that it won't take more than 20s to lose excess heat to ambient
        maxStableAverageShellTemp = (
            (
                brewHeadToAmbientPower * 20.0
                - (self.waterTemp - self.temp_setpoint)
                * config.SPEC_HEAT_WATER_100
                * config.BOILER_VOLUME
            )
            / config.SPEC_HEAT_ALUMINIUM
            / config.MASS_BOILER_SHELL
            + self.temp_setpoint
        )
        logger.debug(f"maxStableAverageShellTemp: {maxStableAverageShellTemp}")
        desiredAverageShellTemp = min(
            desiredAverageShellTemp, maxStableAverageShellTemp
        )
        logger.debug(f"desiredAverageShellTemp: {desiredAverageShellTemp}")

        error = (
            (self.shellTemp - desiredAverageShellTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 2.0
        )
        logger.debug(f"error shellTemp: {error}")
        error += (
            (self.elementTemp - desiredAverageShellTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 2.0
        )
        logger.debug(f"error total (shellTemp + elementTemp): {error}")

        self.heaterPower = (
            shellToBrewHeadPower
            + elementToBrewHeadPower
            + shellToBodyPower
            + elementToBodyPower
            + shellToWaterPower
            + elementToWaterPower
            - (error / 2.0)
        )
        logger.debug(f"ISH LOST {(self.heaterPower + (error * 2.0))} W")
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
        logger.debug(
            f"maxAllowableElementToShellPower {maxAllowableElementToShellPower}"
        )
        maxAllowableElementTemp = (
            maxAllowableElementToShellPower / config.ELEMENT_SHELL_XFER_COEFF
            + self.shellTemp
        )
        logger.debug(f"maxAllowableElementTemp {maxAllowableElementTemp}")
        maxAllowableElementTemp = min(
            maxAllowableElementTemp, config.ELEMENT_MAX_TEMPERATURE
        )
        logger.debug(f"maxAllowableElementTemp {maxAllowableElementTemp}")
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
        logger.debug(f"maxAllowablePowerForElement {maxAllowablePowerForElement}")

        logger.debug(f"heaterPower0 {self.heaterPower}")
        self.heaterPower = min(config.MAX_BOILER_POWER, self.heaterPower)
        logger.debug(f"heaterPower1 {self.heaterPower}")
        self.heaterPower = min(maxAllowablePowerForElement, self.heaterPower)
        logger.debug(f"heaterPower2 {self.heaterPower}")
        self.heaterPower = max(0.0, self.heaterPower)
        logger.debug(f"heaterPower3 {self.heaterPower}")
        normalizedHeaterPower = self.heaterPower / config.MAX_BOILER_POWER
        normalizedHeaterPower = max(normalizedHeaterPower, 0.0)
        normalizedHeaterPower = min(normalizedHeaterPower, 1.0)
        logger.debug(f"heaterPower normalized {normalizedHeaterPower}")

        return min(normalizedHeaterPower, 1.0), (
            self.shellTemp,
            self.elementTemp,
            self.waterTemp,
            self.bodyTemp,
            self.brewHeadTemp,
            self.modeledSensorTemp,
            temperature,
        )
