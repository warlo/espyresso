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


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f").write_text("x")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "c")
    return tmp_path


def test_git_commit_is_read_without_running_git(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Under systemd the app runs as root on a repo owned by pi; git then
    # refuses ("dubious ownership") and the commit came out empty.
    import subprocess

    def no_subprocess(*a: object, **kw: object) -> None:
        raise AssertionError("must not shell out")

    expected = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(subprocess, "run", no_subprocess)

    assert shot_logger.git_commit(str(repo / "sub" / "dir")) == expected


def test_git_commit_reads_packed_refs(repo: Path) -> None:
    expected = _git(repo, "rev-parse", "HEAD")
    _git(repo, "pack-refs", "--all")

    assert shot_logger.git_commit(str(repo)) == expected


def test_git_commit_outside_a_repo_is_empty(tmp_path: Path) -> None:
    assert shot_logger.git_commit(str(tmp_path)) == ""


def test_session_metadata_commit_matches_this_checkout() -> None:
    import subprocess

    here = Path(__file__).resolve().parent
    head = subprocess.run(["git", "-C", str(here), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    assert shot_logger.collect_metadata()["commit"] == head
