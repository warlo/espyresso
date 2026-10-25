#!/usr/bin/env python3
"""Switch the boiler element and the pump off at the GPIO level.

pigpiod keeps a hardware PWM running after its client exits, so a crashed or
killed app would leave the element at its last duty. The systemd unit runs
this before the app starts and after it stops (``python3 -m
espyresso.failsafe``). Falls back to driving the pins low with raspi-gpio when
pigpiod itself is down.
"""
import logging
import subprocess

import pigpio

from espyresso import config

logger = logging.getLogger(__name__)

OUTPUT_GPIOS = (config.BOILER_PWM_GPIO, config.PUMP_OUT_GPIO, config.PUMP_PWM_GPIO)


def outputs_off() -> None:
    try:
        pi = pigpio.pi()
        if pi.connected:
            pi.hardware_PWM(config.BOILER_PWM_GPIO, 0, 0)
            pi.write(config.PUMP_OUT_GPIO, 0)
            pi.hardware_PWM(config.PUMP_PWM_GPIO, 0, 0)
            pi.stop()
            logger.info("outputs off via pigpiod")
            return
    except Exception:
        logger.exception("pigpiod unavailable")

    for gpio in OUTPUT_GPIOS:
        subprocess.run(["raspi-gpio", "set", str(gpio), "op", "dl"], check=False)
    logger.info("outputs off via raspi-gpio")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    outputs_off()
