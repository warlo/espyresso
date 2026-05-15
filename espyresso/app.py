import logging
import os
import signal
import sys
import time
from typing import Any, Optional

import pigpio

from espyresso import config, shot_logger
from espyresso.bluetooth import BluetoothScale
from espyresso.boiler import Boiler
from espyresso.buttons import Buttons
from espyresso.display import Display
from espyresso.flow import Flow
from espyresso.pump import Pump
from espyresso.ranger import Ranger
from espyresso.temperature import Temperature
from espyresso.timer import BrewingTimer
from espyresso.utils import WaveQueue

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure file + stderr logging. Idempotent — safe to call from ``run()``.

    The stderr handler is important for diagnostics: under systemd, stderr
    is captured by the journal, so ``journalctl -u espyresso`` shows live
    output even if the log file isn't accessible."""
    os.makedirs("log", exist_ok=True)
    fmt = "%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S%z"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    file_handler = logging.FileHandler(
        f"log/{time.strftime('%Y-%m-%d-%H:%M')}.log", mode="a"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if config.DEBUG else logging.INFO)
    # basicConfig is a no-op if handlers are already attached, so clear first
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


class Espyresso:
    def __init__(self, pigpio_pi: Optional[pigpio.pi] = None):
        self.started_time = time.perf_counter()
        logger.debug("STARTING ESPYRESSO")

        if config.LOG_SHOT:
            shot_logger.init(config.LOG_SHOT_DIR)

        if not pigpio_pi:
            self.pigpio_pi = pigpio.pi()
        else:
            self.pigpio_pi = pigpio_pi

        self.flow_queue = WaveQueue(
            0,
            3,
            X_MIN=config.FLOW_X_MIN,
            X_MAX=config.FLOW_X_MAX,
            Y_MIN=config.FLOW_Y_MIN,
            Y_MAX=config.FLOW_Y_MAX,
            steps=5,
        )
        self.flow = Flow(
            pigpio_pi=self.pigpio_pi,
            flow_queue=self.flow_queue,
        )
        self.brewing_timer = BrewingTimer(flow=self.flow)

        self.boiler_queue = WaveQueue(
            0,
            100,
            X_MIN=config.BOILER_X_MIN,
            X_MAX=config.BOILER_X_MAX,
            Y_MIN=config.BOILER_Y_MIN,
            Y_MAX=config.BOILER_Y_MAX,
            steps=5,
        )
        self.boiler = Boiler(
            pigpio_pi=self.pigpio_pi,
            boiling=config.DEBUG,
            reset_started_time=self.reset_started_time,
            add_to_queue=self.boiler_queue.add_to_queue,
        )
        self.ranger = Ranger(pigpio_pi=self.pigpio_pi)

        self.temp_queue = WaveQueue(
            90,
            100,
            X_MIN=config.TEMP_X_MIN,
            X_MAX=config.TEMP_X_MAX,
            Y_MIN=config.TEMP_Y_MIN,
            Y_MAX=config.TEMP_Y_MAX,
            target_y=config.TARGET_TEMP,
        )
        self.temperature = Temperature(
            get_started_time=self.get_started_time,
            pigpio_pi=self.pigpio_pi,
            boiler=self.boiler,
            flow=self.flow,
            temp_queue=self.temp_queue,
        )
        self.bluetooth_scale = BluetoothScale()
        self.pump = Pump(
            pigpio_pi=self.pigpio_pi,
            bluetooth_scale=self.bluetooth_scale,
            boiler=self.boiler,
            temperature=self.temperature,
            flow=self.flow,
            reset_started_time=self.reset_started_time,
            brewing_timer=self.brewing_timer,
            ranger=self.ranger,
        )

        self.buttons = Buttons(
            pigpio_pi=self.pigpio_pi,
            boiler=self.boiler,
            temperature=self.temperature,
            pump=self.pump,
            turn_off_system=self.turn_off_system,
        )

        # self.pump.pulse_pump_steam()
        self.display = Display(
            get_started_time=self.get_started_time,
            bluetooth_scale=self.bluetooth_scale,
            boiler=self.boiler,
            buttons=self.buttons,
            brewing_timer=self.brewing_timer,
            pump=self.pump,
            ranger=self.ranger,
            flow=self.flow,
            wave_queues={
                "temp": self.temp_queue,
                "flow": self.flow_queue,
                "boiler": self.boiler_queue,
            },
        )

    def reset_started_time(self) -> None:
        self.started_time = time.perf_counter()

    def get_started_time(self) -> float:
        return self.started_time

    def start(self) -> None:
        self.reset_started_time()

        logger.info("starting temperature thread")
        self.temperature.start()
        logger.info("starting ranger thread")
        self.ranger.start()
        logger.info("starting bluetooth thread")
        self.bluetooth_scale.start()
        # self.brewing_timer.start()
        logger.info("entering display loop")
        self.display.start()
        logger.info("display loop exited")

        self.ranger.join()
        # self.brewing_timer.join()

        logger.info("pigpio stopping")
        self.pigpio_pi.stop()
        sys.exit(0)

    def stop(self) -> None:
        # self.brewing_timer.stop()
        self.bluetooth_scale.stop()
        self.boiler.turn_off_boiler()
        self.ranger.stop()
        self.temperature.stop()
        self.display.stop()
        sl = shot_logger.get()
        if sl is not None:
            sl.close()

    def exit(self) -> None:
        self.stop()
        logger.debug("EXITING: Stopped all")

    def turn_off_system(self) -> None:
        self.stop()
        logger.debug("Triggering shutdown")
        time.sleep(3)
        os.system("shutdown now -h")

    def signal_handler(self, sig: int, *args: Any) -> None:
        if sig == 2:
            print("You pressed CTRL-C!", sig)
        if sig == 15:
            print("SIGTERM - Killing gracefully!")
        self.stop()


def handler(signum: int, *args: Any) -> None:
    """Why is systemd sending sighups?"""
    logger.warning(f"Got a {signum} signal. Doing nothing")


def run() -> None:
    _configure_logging()
    logger.info("constructing Espyresso")
    try:
        if not config.DEBUG:
            espyresso = Espyresso()
        else:
            from espyresso.simulator_mock import get_espyresso_simulator

            espyresso = get_espyresso_simulator()
    except Exception:
        logger.exception("Espyresso construction failed")
        raise
    logger.info("Espyresso constructed, installing signal handlers")

    try:
        signal.signal(signal.SIGHUP, handler)
        signal.signal(signal.SIGINT, espyresso.signal_handler)
        signal.signal(signal.SIGTERM, espyresso.signal_handler)
        espyresso.start()
    except Exception:
        logger.exception("EXCEPTION")
        espyresso.exit()
