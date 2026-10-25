"""Safety layers that do not depend on the thermal model.

``SafetyGuard`` sits between the controller and the PWM and limits the heater
using only the raw sensor reading. ``Watchdog`` is a separate thread that
forces the heater off when control stops, bounds pump run time, runs the
auto-off timer, and feeds systemd's watchdog so a hung process is restarted
(the unit's ExecStopPost then switches the outputs off).
"""
import logging
import os
import socket
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from espyresso import config, shot_logger

if TYPE_CHECKING:
    from espyresso.boiler import Boiler
    from espyresso.flow import Flow
    from espyresso.pump import Pump

logger = logging.getLogger(__name__)


def sd_notify(message: str) -> None:
    """Send a sd_notify(3) message to systemd; no-op outside systemd."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
    except OSError:
        logger.exception("sd_notify(%s) failed", message)


class SafetyGuard:
    def __init__(self) -> None:
        self.fault: Optional[str] = None
        self._runaway_since: Optional[float] = None
        self._runaway_start_temp = 0.0

    def clear(self) -> None:
        self.fault = None
        self._runaway_since = None

    def limit(
        self, *, now: float, temperature: float, heater: float, setpoint: float, flowing: bool
    ) -> Tuple[float, str]:
        """Return the heater value allowed and why it was limited ("" if not)."""
        if self.fault:
            return 0.0, self.fault

        cap = min(setpoint + config.SAFETY_MAX_ABOVE_SETPOINT, config.SAFETY_MAX_TEMPERATURE)
        if temperature > cap:
            self._runaway_since = None
            return 0.0, "overtemp"

        far_below = temperature < setpoint - config.SAFETY_RUNAWAY_BELOW_SETPOINT
        if heater >= 0.9 and far_below and not flowing:
            if self._runaway_since is None:
                self._runaway_since = now
                self._runaway_start_temp = temperature
            elif now - self._runaway_since >= config.SAFETY_RUNAWAY_SECONDS:
                if temperature - self._runaway_start_temp < config.SAFETY_RUNAWAY_MIN_RISE:
                    self.fault = "sensor not responding"
                    return 0.0, self.fault
                # Heating as expected; start a new observation window.
                self._runaway_since = now
                self._runaway_start_temp = temperature
        else:
            self._runaway_since = None

        return heater, ""


class Watchdog(threading.Thread):
    def __init__(
        self,
        *,
        boiler: "Boiler",
        pump: Optional["Pump"],
        flow: "Flow",
        get_started_time: Callable[[], float],
        reset_started_time: Callable[[], None],
        notify: Callable[[str], None] = sd_notify,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        super().__init__(name="watchdog", daemon=True)
        self.boiler = boiler
        self.pump = pump
        self.flow = flow
        self.get_started_time = get_started_time
        self.reset_started_time = reset_started_time
        self.notify = notify
        self.clock = clock

        self._last_control: Optional[float] = None
        self._was_fresh = False
        self._had_control = False
        self._ready_sent = False
        self._pump_on_since: Optional[float] = None
        self._flow_seen_ml = flow.lifetime_ml
        self._stop_event = threading.Event()

    def heartbeat(self) -> None:
        """Called by the control loop after each completed tick."""
        self._last_control = self.clock()

    def control_is_fresh(self) -> bool:
        return (
            self._last_control is not None
            and self.clock() - self._last_control < config.CONTROL_STALE_SECONDS
        )

    def check(self) -> None:
        now = self.clock()
        fresh = self.control_is_fresh()
        sl = shot_logger.get()

        if not fresh:
            self.boiler.force_off()
            if self._was_fresh:
                logger.error("control stale: heater forced off")
                if sl is not None:
                    sl.log_event("safety", reason="control_stale")
        elif not self._was_fresh and self._last_control is not None and sl is not None:
            sl.log_event(
                "safety",
                reason="control_resumed" if self._had_control else "control_started",
            )
        self._was_fresh = fresh
        self._had_control = self._had_control or fresh

        if self.pump is not None and self.pump.pumping:
            if self._pump_on_since is None:
                self._pump_on_since = now
            elif now - self._pump_on_since > config.PUMP_MAX_ON_SECONDS:
                logger.error("pump on for %.0f s: stopping", now - self._pump_on_since)
                self.pump.stop_pump()
                self._pump_on_since = None
                if sl is not None:
                    sl.log_event("safety", reason="pump_max_on")
        else:
            self._pump_on_since = None

        if self.flow.lifetime_ml - self._flow_seen_ml >= config.AUTO_OFF_MIN_FLOW_ML:
            self._flow_seen_ml = self.flow.lifetime_ml
            self.reset_started_time()
        if (
            self.boiler.get_boiling()
            and now - self.get_started_time() > config.TURN_OFF_SECONDS
        ):
            self.boiler.turn_off_boiler()
            if sl is not None:
                sl.log_event("auto_off", idle_seconds=now - self.get_started_time())

        if fresh:
            if not self._ready_sent:
                self.notify("READY=1")
                self._ready_sent = True
            self.notify("WATCHDOG=1")

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check()
            except Exception:
                logger.exception("watchdog check failed")
                try:
                    self.boiler.force_off()
                except Exception:
                    logger.exception("watchdog could not force the heater off")
            self._stop_event.wait(config.WATCHDOG_INTERVAL)

    def stop(self) -> None:
        self._stop_event.set()
