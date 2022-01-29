#!/usr/bin/env python3
import logging
import threading
import time
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from espyresso.flow import Flow


class Timer:
    def __init__(
        self,
    ) -> None:
        self.started: Optional[float] = None
        self.stopped: Optional[float] = None

    def get_time_since_started(self) -> float:
        if self.stopped and self.started:
            return self.stopped - self.started
        if self.started:
            return time.time() - self.started
        return 0

    def timer_running(self) -> bool:
        return bool(self.started and not self.stopped)

    def start_timer(self) -> None:
        self.stopped = None
        self.started = time.time()

    def stop_timer(self, *, subtract_time=0) -> None:
        self.stopped = time.time() - subtract_time

    def reset_timer(self) -> None:
        self.stopped = None
        self.stopped = None


class BrewingTimer(threading.Thread):
    def __init__(self, flow: "Flow", *args, **kwargs):
        self._stop_event = threading.Event()

        self.flow = flow
        self.started: Optional[float] = None
        self.stopped: Optional[float] = None
        super().__init__(*args, **kwargs)

    def get_time_since_started(self) -> float:
        if self.stopped and self.started:
            return self.stopped - self.started
        if self.started:
            return time.time() - self.started
        return 0

    def get_time_since_stopped(self) -> float:
        if self.stopped:
            return time.time() - self.stopped
        return 999999

    def timer_running(self) -> bool:
        return bool(self.started and not self.stopped)

    def start_timer(self) -> None:
        self.stopped = None
        self.started = time.time()

    def stop_timer(self, *, subtract_time=0) -> None:
        self.stopped = time.time() - subtract_time

    def reset_timer(self) -> None:
        self.stopped = None
        self.stopped = None

    def stop(self) -> None:
        logger.debug("Brewingtimer stopping")
        self._stop_event.set()
        logger.debug("Brewingtimer stopped")

    def run(self) -> None:
        while not self._stop_event.is_set():

            if (
                not self.timer_running()
                and (self.get_time_since_stopped() > 3)
                and self.flow.get_time_since_last_pulse() < 1
            ):
                self.flow.reset_pulse_count()
                self.start_timer()

            elif self.timer_running() and self.flow.get_time_since_last_pulse() > 1:
                self.stop_timer(subtract_time=self.flow.get_time_since_last_pulse())

            time.sleep(0.2)
