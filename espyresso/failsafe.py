#!/usr/bin/env python3
"""Switch the boiler element and the pump off at the GPIO level.

pigpiod keeps a hardware PWM running after its client exits, so a crashed or
killed app would leave the element at its last duty. The systemd unit runs
this before the app starts and after it stops (``python3 -m
espyresso.failsafe``). Falls back to driving the pins low with raspi-gpio when
pigpiod itself is down.

It also resets virtual consoles a killed app left in graphics mode: the kernel
ignores every console switch away from such a console, so the next start's
display (SDL fbcon waits for its switch) would hang forever.
"""
import fcntl
import logging
import os
import struct
import subprocess

import pigpio

from espyresso import config

logger = logging.getLogger(__name__)

OUTPUT_GPIOS = (config.BOILER_PWM_GPIO, config.PUMP_OUT_GPIO, config.PUMP_PWM_GPIO)

KDGETMODE, KDSETMODE = 0x4B3B, 0x4B3A
KD_TEXT, KD_GRAPHICS = 0, 1


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


def reset_stale_consoles(max_vt: int = 12) -> None:
    """Put virtual consoles left in graphics mode back into text mode. Only
    call while no display is running (before start-up, after a stop)."""
    for n in range(1, max_vt + 1):
        path = "/dev/tty%d" % n
        try:
            fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        except OSError:
            continue
        try:
            mode = struct.unpack("i", fcntl.ioctl(fd, KDGETMODE, b"\0" * 4))[0]
            if mode == KD_GRAPHICS:
                fcntl.ioctl(fd, KDSETMODE, KD_TEXT)
                logger.warning("%s was left in graphics mode: reset to text", path)
        except OSError:
            logger.exception("could not check %s", path)
        finally:
            os.close(fd)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    outputs_off()
    reset_stale_consoles()
