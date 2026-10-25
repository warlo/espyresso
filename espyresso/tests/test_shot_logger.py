"""Tests for ``espyresso.shot_logger``: what lands on disk for later analysis."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from espyresso import config, shot_logger


def test_tick_rows_reach_disk_periodically_without_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shot_logger.ShotLogger, "FLUSH_SECONDS", 0.05)
    sl = shot_logger.ShotLogger(str(tmp_path))
    sl.log_tick(raw_temp=95.0)
    time.sleep(0.1)
    sl.log_tick(raw_temp=95.1)

    # Read without closing: a crash or power cut never gets to close().
    rows = Path(sl.tick_path).read_text().splitlines()
    assert len(rows) >= 2  # header + at least the first row
    sl.close()


def test_session_metadata_records_config_and_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TARGET_TEMP", 97.25)
    sl = shot_logger.ShotLogger(str(tmp_path))

    sl.write_meta(shot_logger.collect_metadata())

    meta = json.loads(Path(sl.meta_path).read_text())
    assert meta["config"]["TARGET_TEMP"] == 97.25
    assert "commit" in meta
    sl.close()


def test_close_twice_is_safe(tmp_path: Path) -> None:
    # stop() can run twice: signal handler, then the exit path.
    sl = shot_logger.ShotLogger(str(tmp_path))
    sl.log_tick(raw_temp=95.0)
    sl.close()
    sl.close()
