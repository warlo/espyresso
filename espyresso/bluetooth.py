import logging
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Optional

from espyresso import config, shot_logger

logger = logging.getLogger(__name__)


def _spawn_scale_process() -> "subprocess.Popen[str]":
    return subprocess.Popen(
        [sys.executable, "-m", "espyresso.scale"],
        stdout=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        universal_newlines=True,
        bufsize=1,
    )


class BluetoothScale:
    """The Eureka Precisa. Bluetooth runs in its own low-priority process
    (espyresso.scale) so it can't hold up temperature decoding; this side
    keeps its latest reading and starts it again if it dies."""

    def __init__(self, spawn: Callable[[], Any] = _spawn_scale_process) -> None:
        self._spawn = spawn
        self.process: Any = None
        self.current_weight = 0.0
        self.current_weight_timestamp = 0.0
        self._logged_weight: Optional[float] = None
        self._logged_at = 0.0
        self._stopping = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def get_scale_weight(self) -> float:
        if time.perf_counter() - self.current_weight_timestamp > 5:
            return 0
        return self.current_weight

    def start(self) -> None:
        if config.DEBUG:
            # Skip bluetooth in debug
            return
        if not config.BLUETOOTH_ENABLED:
            logger.info("bluetooth disabled via config.BLUETOOTH_ENABLED")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._supervise, name="scale", daemon=True)
        self._thread.start()

    def _supervise(self) -> None:
        while not self._stopping.is_set():
            try:
                self.process = self._spawn()
                for line in iter(self.process.stdout.readline, ""):
                    self.handle_line(line)
                self.process.wait(timeout=5)
            except Exception:
                logger.exception("scale process failed")
            if not self._stopping.is_set():
                logger.warning("scale process ended; starting it again")
                self._stopping.wait(config.BLUETOOTH_RESTART_SECONDS)

    def stop(self) -> None:
        self._stopping.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()

    def request_connect(self) -> None:
        """Search for the scale now instead of after the back-off, e.g. a
        shot is starting and the scale was just woken. Safe from any thread."""
        process = self.process
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGUSR1)

    def handle_line(self, line: str) -> None:
        """One line from the scale process (see espyresso.scale)."""
        parts = line.split()
        if len(parts) == 2 and parts[0] == "w":
            try:
                grams = float(parts[1])
            except ValueError:
                return
            self._store(grams)
        elif len(parts) == 2 and parts[0] == "link":
            self._log_connection(parts[1])

    def _store(self, grams: float) -> None:
        now = time.perf_counter()
        self.current_weight = grams
        self.current_weight_timestamp = now
        # The scale notifies several times a second: log changes, at most once
        # a second, so the Pi Zero isn't writing an event per notification.
        if grams != self._logged_weight and now - self._logged_at >= 1.0:
            self._logged_weight, self._logged_at = grams, now
            sl = shot_logger.get()
            if sl is not None:
                sl.log_event("scale", grams=grams)

    def _log_connection(self, state: str) -> None:
        logger.info("scale %s", state)
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("scale_link", state=state)
