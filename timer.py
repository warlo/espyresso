#!/usr/bin/env python3
import time


class Timer:
    def __init__(
        self,
    ):
        self.started = None
        self.stopped = None

    def get_time_since_started(self):
        if self.stopped and self.started:
            return self.stopped - self.started
        if self.started:
            return time.time() - self.started
        return 0

    def running(self):
        return self.started and not self.stopped

    def start_timer(self):
        self.stopped = None
        self.started = time.time()

    def stop_timer(self, *, subtract_time=0):
        self.stopped = time.time() - subtract_time

    def reset_timer(self):
        self.stopped = None
        self.stopped = None
