import logging
import math
import threading
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from espyresso import config, shot_logger
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

        # Serialises PWM writes from the control thread against turn-off and
        # force-off from other threads, so a late control write can never
        # land after the element was switched off.
        self._lock = threading.RLock()

        self.pwm_override: Optional[float] = None
        self.set_pwm_override(None)
        self.add_to_queue = add_to_queue
        # Why safety switched the boiler off (shown on the display); cleared
        # when the user switches it on again.
        self.fault: Optional[str] = None

        # No blind heating here: the element stays off until the controller
        # has a measurement. The warm-up boost lives in the controller,
        # sized from the first reading (see PController.start_boost).

        logger.debug("Boiler READY")

    def get_boiling(self) -> bool:
        return self.boiling

    def turn_off_boiler(self) -> None:
        logger.debug("Boiler stopping")
        with self._lock:
            self.boiling = False
            self.set_pwm_override(None)
            self.pwm.set_value(0)
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("boiler", state="off")
        logger.debug("Boiler stopped")

    def turn_on_boiler(self) -> None:
        self.fault = None
        self.boiling = True
        self.reset_started_time()
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("boiler", state="on")

    def toggle_boiler(self) -> None:
        self.boiling = not self.get_boiling()
        if not self.boiling:
            self.pwm.set_value(0)
        else:
            self.fault = None
            self.reset_started_time()
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event(
                "boiler", state="on" if self.boiling else "off", source="toggle"
            )

    def force_off(self) -> None:
        """Write 0 to the element regardless of boiling state or override.
        Does not change ``boiling``, so control resumes when healthy."""
        with self._lock:
            self.pwm.set_value(0)

    def set_pwm_override(self, value: Optional[float]) -> None:
        with self._lock:
            self.pwm_override = value

            if self.pwm_override:
                self.pwm.set_value(self.pwm_override)
            else:
                self.pwm.set_value(0)
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("boiler_override", value=value)

    def set_value(self, value: float) -> None:
        if not math.isfinite(value):
            # min()/max() pass NaN straight through; never let it reach the PWM.
            value = 0.0

        with self._lock:
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
