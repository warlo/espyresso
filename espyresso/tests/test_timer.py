"""Tests for ``espyresso.timer``.

The ``reset_timer`` method on both ``Timer`` and ``BrewingTimer``
currently has a bug — it writes ``self.stopped = None`` twice instead of
also clearing ``self.started`` — so any test that calls it expecting
``get_time_since_started()`` to return 0 after a reset is **expected to
fail** until the fix lands. Those tests are kept in this file (not
xfail-marked) so that the fix is verifiable by re-running the suite.
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from espyresso.timer import BrewingTimer, Timer


# ----------------------- Timer ----------------------------------------- #


def test_timer_returns_zero_before_start() -> None:
    timer = Timer()
    assert timer.get_time_since_started() == 0


def test_timer_running_after_start() -> None:
    timer = Timer()
    timer.start_timer()
    assert timer.timer_running() is True
    assert timer.get_time_since_started() >= 0


def test_timer_not_running_after_stop() -> None:
    timer = Timer()
    timer.start_timer()
    timer.stop_timer()
    assert timer.timer_running() is False


def test_timer_elapsed_freezes_after_stop() -> None:
    timer = Timer()
    timer.start_timer()
    time.sleep(0.02)
    timer.stop_timer()
    elapsed_at_stop = timer.get_time_since_started()
    time.sleep(0.02)
    # Frozen — get_time_since_started returns the same value
    assert timer.get_time_since_started() == pytest.approx(elapsed_at_stop)


def test_timer_stop_with_subtract_time() -> None:
    timer = Timer()
    timer.start_timer()
    time.sleep(0.05)
    timer.stop_timer(subtract_time=1)
    # subtracted second pushes stopped before started → negative elapsed
    assert timer.get_time_since_started() < 0


def test_timer_reset_clears_started() -> None:
    """Regression: reset_timer must zero ``started`` so a fresh start
    timer begins at 0. Currently FAILS — the production code's
    ``reset_timer`` accidentally rewrites ``stopped`` twice."""
    timer = Timer()
    timer.start_timer()
    time.sleep(0.02)
    timer.stop_timer()
    timer.reset_timer()
    assert timer.get_time_since_started() == 0


# ----------------------- BrewingTimer --------------------------------- #


def make_brewing_timer() -> BrewingTimer:
    flow = Mock()
    flow.prev_pulse_time = time.perf_counter()
    return BrewingTimer(flow=flow)


def test_brewing_timer_initial_state() -> None:
    bt = make_brewing_timer()
    assert bt.timer_running() is False
    assert bt.get_time_since_started() == 0
    assert bt.enable_automatic_timing_flag is True


def test_brewing_timer_start_stop_elapsed() -> None:
    bt = make_brewing_timer()
    bt.start_timer()
    assert bt.timer_running() is True
    time.sleep(0.02)
    bt.stop_timer()
    assert bt.timer_running() is False
    assert bt.get_time_since_started() > 0


def test_brewing_timer_disable_automatic_timing() -> None:
    bt = make_brewing_timer()
    bt.disable_automatic_timing()
    assert bt.enable_automatic_timing_flag is False
    bt.enable_automatic_timing()
    assert bt.enable_automatic_timing_flag is True


def test_brewing_timer_get_time_since_stopped_when_never_stopped() -> None:
    bt = make_brewing_timer()
    # Sentinel value used by the run loop to mean "very long ago"
    assert bt.get_time_since_stopped() == 999999


def test_brewing_timer_get_time_since_stopped_after_stop() -> None:
    bt = make_brewing_timer()
    bt.start_timer()
    bt.stop_timer()
    time.sleep(0.02)
    assert bt.get_time_since_stopped() >= 0.02


def test_brewing_timer_reset_clears_started() -> None:
    """Regression — same bug as Timer.reset_timer."""
    bt = make_brewing_timer()
    bt.start_timer()
    time.sleep(0.02)
    bt.stop_timer()
    bt.reset_timer()
    assert bt.get_time_since_started() == 0
