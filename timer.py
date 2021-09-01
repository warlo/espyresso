#!/usr/bin/env python3
import threading
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

    def timer_running(self):
        return self.started and not self.stopped

    def start_timer(self):
        self.stopped = None
        self.started = time.time()

    def stop_timer(self, *, subtract_time=0):
        self.stopped = time.time() - subtract_time

    def reset_timer(self):
        self.stopped = None
        self.stopped = None


class BrewingTimer(threading.Thread, Timer):
    def __init__(self, flow=None):
        self.running = True
        self.flow = flow

    def stop(self):
        self.running = False

    def run(self):
        while self.running:

            if not self.timer_running() and self.flow.get_time_since_last_pulse() < 1:
                self.start_timer()

            elif self.timer_running() and self.flow.get_time_since_last_pulse() > 1:
                self.stop_timer(subtract_time=self.flow.get_time_since_last_pulse())

            time.sleep(0.5)
