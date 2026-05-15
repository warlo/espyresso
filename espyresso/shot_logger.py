#!/usr/bin/env python3
"""Structured CSV logger for reviewing real-life shots against the MPC.

Writes two line-buffered files per session in ``base_dir`` (default ``log/``):

- ``shot-<ts>-tick.csv``  one row per controller update (~ TSIC sample rate).
  Column header is inferred from the first ``log_tick`` call, so the caller
  decides the schema.
- ``shot-<ts>-event.csv``  ``t,kind,details`` for discrete events.

A single process-wide instance is exposed via :func:`init` / :func:`get` so
modules deep in the call graph (pcontroller, boiler, pump, buttons, ...) can
emit without threading a dependency through every constructor.
"""
import logging
import math
import os
import threading
import time
from typing import Any, List, Optional, TextIO

logger = logging.getLogger(__name__)

_INSTANCE: Optional["ShotLogger"] = None


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        return f"{v:.4f}"
    if isinstance(v, str):
        # CSV-safe: strip commas and newlines from free-form details.
        return v.replace(",", ";").replace("\n", " ")
    return str(v)


class ShotLogger:
    def __init__(self, base_dir: str = "log") -> None:
        os.makedirs(base_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.tick_path = os.path.join(base_dir, f"shot-{ts}-tick.csv")
        self.event_path = os.path.join(base_dir, f"shot-{ts}-event.csv")
        self._tick_file: Optional[TextIO] = None
        self._tick_keys: List[str] = []
        self._event_file: TextIO = open(self.event_path, "w", buffering=1)
        self._event_file.write("t,kind,details\n")
        self._lock = threading.Lock()
        self._t0 = time.perf_counter()
        logger.info(
            "ShotLogger started: tick=%s event=%s", self.tick_path, self.event_path
        )

    def _now(self) -> float:
        return time.perf_counter() - self._t0

    def log_tick(self, **fields: Any) -> None:
        try:
            with self._lock:
                if self._tick_file is None:
                    self._tick_keys = ["t"] + list(fields.keys())
                    self._tick_file = open(self.tick_path, "w", buffering=1)
                    self._tick_file.write(",".join(self._tick_keys) + "\n")
                row = [f"{self._now():.4f}"]
                row.extend(_fmt(fields.get(k)) for k in self._tick_keys[1:])
                self._tick_file.write(",".join(row) + "\n")
        except Exception:
            logger.exception("ShotLogger.log_tick failed")

    def log_event(self, kind: str, **fields: Any) -> None:
        try:
            with self._lock:
                details = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
                self._event_file.write(f"{self._now():.4f},{kind},{details}\n")
        except Exception:
            logger.exception("ShotLogger.log_event failed")

    def close(self) -> None:
        with self._lock:
            if self._tick_file is not None:
                self._tick_file.close()
                self._tick_file = None
            self._event_file.close()


def init(base_dir: str = "log") -> ShotLogger:
    global _INSTANCE
    _INSTANCE = ShotLogger(base_dir)
    return _INSTANCE


def get() -> Optional[ShotLogger]:
    return _INSTANCE
