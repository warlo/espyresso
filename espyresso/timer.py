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
            return time.perf_counter() - self.started
        return 0

    def timer_running(self) -> bool:
        return bool(self.started and not self.stopped)

    def start_timer(self) -> None:
        self.stopped = None
        self.started = time.perf_counter()

    def stop_timer(self, *, subtract_time=0) -> None:
        self.stopped = time.perf_counter() - subtract_time

    def reset_timer(self) -> None:
        self.stopped = None
        self.stopped = None


class BrewingTimer(threading.Thread):
    def __init__(self, flow: "Flow", *args, **kwargs):
        self._stop_event = threading.Event()

        self.flow = flow
        self.enable_automatic_timing_flag = True
        self.started: Optional[float] = None
        self.stopped: Optional[float] = None
        super().__init__(*args, **kwargs)

    def get_time_since_started(self) -> float:
        logger.debug(f"TIME since started {self.started}, {self.stopped}")
        if self.stopped and self.started:
            return self.stopped - self.started
        if self.started:
            return time.perf_counter() - self.started
        return 0

    def disable_automatic_timing(self) -> None:
        self.enable_automatic_timing_flag = False

    def enable_automatic_timing(self) -> None:
        self.enable_automatic_timing_flag = True

    def get_time_since_stopped(self) -> float:
        if self.stopped:
            return time.perf_counter() - self.stopped
        return 999999

    def timer_running(self) -> bool:
        return bool(self.started and not self.stopped)

    def start_timer(self) -> None:
        logger.debug("Starting timer")
        self.stopped = None
        self.started = time.perf_counter()

    def stop_timer(self, *, subtract_time: float = 0) -> None:
        logger.debug("Stopping timer")
        self.stopped = time.perf_counter() - subtract_time

    def reset_timer(self) -> None:
        self.stopped = None
        self.stopped = None

    def stop(self) -> None:
        logger.debug("Brewingtimer stopping")
        self._stop_event.set()
        logger.debug("Brewingtimer stopped")

    def run(self) -> None:
        while not self._stop_event.is_set():

            # Skip timer thread while automatic pumping e.g. brew shot routine
            if not self.enable_automatic_timing_flag:
                time.sleep(1)
                continue

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
