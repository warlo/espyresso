import logging
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from espyresso import config
from espyresso.pwm import PWM

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pigpio import pi


class Boiler:
    def __init__(
        self,
        pigpio_pi: "pi",
        reset_started_time: Callable[[], None],
        add_to_queue: Callable[[Tuple[float, ...]], None],
        boiling: bool = False,
    ):
        logger.debug(f"Boiler INIT: gpio {config.BOILER_PWM_GPIO} boiling {boiling}")

        self.pwm = PWM(pigpio_pi, config.BOILER_PWM_GPIO, 2)
        self.boiling = boiling
        self.reset_started_time = reset_started_time

        self.pwm_override: Optional[float] = None
        self.set_pwm_override(None)
        self.add_to_queue = add_to_queue

        if self.boiling and not config.DEBUG:
            # Start boiling initially
            self.pwm.set_value(1.0)

        logger.debug("Boiler READY")

    def get_boiling(self) -> bool:
        return self.boiling

    def turn_off_boiler(self) -> None:
        self.boiling = False
        self.pwm.set_value(0)

    def toggle_boiler(self) -> None:
        self.boiling = not self.get_boiling()
        if not self.boiling:
            self.pwm.set_value(0)
        else:
            self.reset_started_time()

    def set_pwm_override(self, value: Optional[float]) -> None:
        self.pwm_override = value

        if self.pwm_override:
            self.pwm.set_value(self.pwm_override)
        else:
            self.pwm.set_value(0)

    def set_value(self, value: float) -> None:
        if not self.get_boiling():
            return

        if self.pwm_override:
            return

        if value < 0.0:
            value = 0.0
        elif value > 1.0:
            value = 1.0

        self.pwm.set_value(value)
        self.add_to_queue(tuple((round(value * 100, 1),)))

    def stop(self) -> None:
        logger.debug("Boiler stopping")
        self.set_pwm_override(None)
        self.set_value(0)
        logger.debug("Boiler stopped")
