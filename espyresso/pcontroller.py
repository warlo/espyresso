#!/usr/bin/env python3

import time
from typing import TYPE_CHECKING

from espyresso import config

if TYPE_CHECKING:
    from espyresso.flow import Flow


class PController:
    def __init__(self, initial_temperature: float, flow: "Flow") -> None:

        self.elementTemp = initial_temperature
        self.shellTemp = self.elementTemp

        self.ambientTemp = min(self.shellTemp, config.AMBIENT_TEMPERATURE)

        self.waterTemp = self.shellTemp

        # based on heat transfer coefficients to and from brewhead, we can caluculate its steady state temp - use that
        self.brewHeadTemp = (
            self.ambientTemp * config.BREWHEAD_AMBIENT_XFER_COEFF
            + self.shellTemp * config.BOILER_BREWHEAD_XFER_COEFF
        ) / (config.BREWHEAD_AMBIENT_XFER_COEFF + config.BOILER_BREWHEAD_XFER_COEFF)

        self.bodyTemp = self.shellTemp

        self.pumpPowerRate = 0.0
        self.heaterPower = 0.0
        self.lastBoilerPidTime: float = 0.0
        self.flow = flow

    def update(self, temperature: float) -> tuple[float, tuple[float, ...]]:
        print("\n")
        current_time = time.perf_counter()
        print("CURRENT_TIME:", current_time)
        deltaTime = current_time - self.lastBoilerPidTime
        print("deltaTime:", deltaTime)
        self.lastBoilerPidTime = current_time
        print("lastBoilerPidTime:", self.lastBoilerPidTime)

        self.flowRate = self.flow.get_millilitres_per_sec() or 0
        print("FLOWRATE", self.flowRate)

        # TODO: verify flow
        waterToFlowPower = (
            self.flowRate
            * (self.waterTemp - config.RESERVOIR_TEMPERATURE)
            * config.SPEC_HEAT_WATER_100
        )
        print("waterToFlowPower:", waterToFlowPower)

        # How much power is lost to the atmosphere from the brew head?
        brewHeadToAmbientPower = (
            self.brewHeadTemp - self.ambientTemp
        ) * config.BREWHEAD_AMBIENT_XFER_COEFF
        print("brewHeadToAmbientPower:", brewHeadToAmbientPower)

        # How much power is transferred from the boiler to the water?
        shellToWaterPower = (
            (self.shellTemp - self.waterTemp)
            * config.BOILER_WATER_XFER_COEFF_NOFLOW
            / 2.0
        )
        print("shellToWaterPower:", shellToWaterPower)
        elementToWaterPower = (
            (self.elementTemp - self.waterTemp)
            * config.BOILER_WATER_XFER_COEFF_NOFLOW
            / 2.0
        )
        print("elementToWaterPower:", elementToWaterPower)

        # How much power is transferred from the boiler to the brew head?
        shellToBrewHeadPower = (
            (self.shellTemp - self.brewHeadTemp)
            * config.BOILER_BREWHEAD_XFER_COEFF
            / 2.0
        )
        print("shellToBrewHeadPower:", shellToBrewHeadPower)
        elementToBrewHeadPower = (
            (self.elementTemp - self.brewHeadTemp)
            * config.BOILER_BREWHEAD_XFER_COEFF
            / 2.0
        )
        print("elementToBrewHeadPower:", elementToBrewHeadPower)
        # TODO: FLOW POWER?
        waterFlowToBrewHeadPower = (
            (self.waterTemp - self.brewHeadTemp)
            * self.flowRate
            * config.SPEC_HEAT_WATER_100
        )
        print("waterFlowToBrewHeadPower:", waterFlowToBrewHeadPower)
        elementToShellPower = (
            self.elementTemp - self.shellTemp
        ) * config.ELEMENT_SHELL_XFER_COEFF
        print("elementToShellPower:", elementToShellPower)
        shellToBodyPower = (
            (self.shellTemp - self.bodyTemp) * config.BOILER_BODY_XFER_COEFF / 2.0
        )
        print("shellToBodyPower:", shellToBodyPower)
        elementToBodyPower = (
            (self.elementTemp - self.bodyTemp) * config.BOILER_BODY_XFER_COEFF / 2.0
        )
        print("elementToBodyPower:", elementToBodyPower)

        # Now work out the temperature, which comes from power that didn't go into heat loss or heating the incoming water.
        print("\nTEMP:")
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
        print("brewHeadTemp:", self.brewHeadTemp)
        self.waterTemp += (
            deltaTime
            * (shellToWaterPower + elementToWaterPower - waterToFlowPower)
            / (config.SPEC_HEAT_WATER_100 * config.BOILER_VOLUME)
        )
        print("waterTemp:", self.waterTemp)
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
        print("shellTemp:", self.shellTemp)
        self.elementTemp += (
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
        print("elementTemp:", self.elementTemp)
        self.bodyTemp += (
            deltaTime
            * (shellToBodyPower + elementToBodyPower)
            / config.HEAT_CAPACITY_BODY
        )
        print("bodyTemp:", self.bodyTemp)

        # SET ELEMENT TEMP
        # self.elementTemp = temperature
        print("ELEMENTTEMP SET:", self.elementTemp)

        # arrange heater power so that the average boiler energy will be correct in 2 seconds (if possible)
        # the error term handles boiler shell and water - other known power sinks are added explicitly

        # we want the water to reach target temperature in the next 15s so calculate the necessary average temperature of the shell
        desiredWaterInputPower = (
            (config.BREW_SETPOINT - self.waterTemp)
            * config.SPEC_HEAT_WATER_100
            * config.BOILER_VOLUME
            / 15.0
        )
        desiredWaterInputPower += waterToFlowPower
        print("desiredWaterInputPower:", desiredWaterInputPower)

        desiredAverageShellTemp = (
            self.waterTemp
            + desiredWaterInputPower / config.BOILER_WATER_XFER_COEFF_NOFLOW
        )
        print("desiredAverageShellTemp:", desiredAverageShellTemp)

        # TODO: Flow 0
        if self.flowRate > 1.0:
            desiredAverageShellTemp = self.waterTemp + desiredWaterInputPower / 25.0

        # now clip the temperature so that it won't take more than 20s to lose excess heat to ambient
        maxStableAverageShellTemp = (
            (
                brewHeadToAmbientPower * 20.0
                - (self.waterTemp - config.BREW_SETPOINT)
                * config.SPEC_HEAT_WATER_100
                * config.BOILER_VOLUME
            )
            / config.SPEC_HEAT_ALUMINIUM
            / config.MASS_BOILER_SHELL
            + config.BREW_SETPOINT
        )
        print("maxStableAverageShellTemp:", maxStableAverageShellTemp)
        desiredAverageShellTemp = min(
            desiredAverageShellTemp, maxStableAverageShellTemp
        )
        print("desiredAverageShellTemp:", desiredAverageShellTemp)

        error = (
            (self.shellTemp - desiredAverageShellTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 2.0
        )
        print("error shellTemp:", error)
        error += (
            (self.elementTemp - desiredAverageShellTemp)
            * config.SPEC_HEAT_ALUMINIUM
            * config.MASS_BOILER_SHELL
            / 2.0
        )
        print("error total (shellTemp + elementTemp):", error)

        self.heaterPower = (
            shellToBrewHeadPower
            + elementToBrewHeadPower
            + shellToBodyPower
            + elementToBodyPower
            + shellToWaterPower
            + elementToWaterPower
            - (error / 2.0)
        )
        print("ISH LOST", (self.heaterPower + (error * 2.0)), "W")
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
        print("maxAllowableElementToShellPower", maxAllowableElementToShellPower)
        maxAllowableElementTemp = (
            maxAllowableElementToShellPower / config.ELEMENT_SHELL_XFER_COEFF
            + self.shellTemp
        )
        print("maxAllowableElementTemp", maxAllowableElementTemp)
        maxAllowableElementTemp = min(
            maxAllowableElementTemp, config.ELEMENT_MAX_TEMPERATURE
        )
        print("maxAllowableElementTemp", maxAllowableElementTemp)
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
        print("maxAllowablePowerForElement", maxAllowablePowerForElement)

        print("heaterPower0", self.heaterPower)
        self.heaterPower = min(config.MAX_BOILER_POWER, self.heaterPower)
        print("heaterPower1", self.heaterPower)
        self.heaterPower = min(maxAllowablePowerForElement, self.heaterPower)
        print("heaterPower2", self.heaterPower)
        self.heaterPower = max(0.0, self.heaterPower)
        print("heaterPower3", self.heaterPower)
        normalizedHeaterPower = self.heaterPower / config.MAX_BOILER_POWER
        normalizedHeaterPower = max(normalizedHeaterPower, 0.0)
        normalizedHeaterPower = min(normalizedHeaterPower, 1.0)
        print("heaterPower normalized", normalizedHeaterPower)

        return min(normalizedHeaterPower, 1.0), (
            self.shellTemp,
            self.waterTemp,
            self.elementTemp,
        )
