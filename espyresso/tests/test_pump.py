"""Tests for ``espyresso.pump.Pump`` shot bookkeeping.

The brew routine's end-of-shot path runs both from the pump thread and
from button callbacks on pigpio's notification thread. An exception there
kills every GPIO callback (including the temperature sensor), so the
end-of-shot path must never raise and must log each shot exactly once.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterator
from unittest.mock import Mock

import pytest

from espyresso import config, shot_logger
from espyresso.flow import Flow
from espyresso.pump import Pump
from espyresso.timer import BrewingTimer
from espyresso.utils import WaveQueue


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(config, "SHOT_STAT_FILE", str(tmp_path / "shot_stat.txt"))
    sl = shot_logger.init(str(tmp_path))
    yield tmp_path
    sl.close()
    # Plain assignment: a monkeypatch made during teardown would be undone,
    # restoring the closed logger for later tests.
    shot_logger._INSTANCE = None


@pytest.fixture
def flow() -> Flow:
    return Flow(pigpio_pi=Mock(), flow_queue=WaveQueue(0, 3, X_MIN=0, X_MAX=10, Y_MIN=0, Y_MAX=10))


@pytest.fixture
def timer(flow: Flow) -> BrewingTimer:
    return BrewingTimer(flow=flow)


@pytest.fixture
def pump(flow: Flow, timer: BrewingTimer) -> Iterator[Pump]:
    scale = Mock()
    scale.get_scale_weight.return_value = 0
    p = Pump(
        pigpio_pi=Mock(),
        bluetooth_scale=scale,
        boiler=Mock(),
        temperature=Mock(),
        flow=flow,
        reset_started_time=Mock(),
        brewing_timer=timer,
        ranger=Mock(),
    )
    yield p
    # A failing routine test must not leave its thread pumping (and holding
    # the test run open for the routine's full duration).
    p.reset()
    if p.pump_thread.is_alive():
        p.pump_thread.join(timeout=3)


def _finish_shot(pump: Pump, timer: BrewingTimer, flow: Flow, seconds: float, ml: float) -> None:
    # reset_brew_routine stops the timer "now", so the shot started `seconds` ago.
    timer.started = time.perf_counter() - seconds
    timer.stopped = None
    flow.total_volume = ml
    pump.started_preinfuse = 90.0
    pump.stopped_preinfuse = 97.0


def test_reset_brew_routine_logs_brew_end_event(log_dir: Path, pump: Pump, timer: BrewingTimer, flow: Flow) -> None:
    _finish_shot(pump, timer, flow, seconds=28.0, ml=41.0)
    pump._brew_active = True

    pump.reset_brew_routine()

    events = (log_dir / Path(shot_logger.get().event_path).name).read_text()  # type: ignore[union-attr]
    end = [line for line in events.splitlines() if ",brew," in line and "phase=end" in line]
    assert len(end) == 1
    shot_seconds = float(re.search(r"shot_seconds=([\d.]+)", end[0]).group(1))  # type: ignore[union-attr]
    assert shot_seconds == pytest.approx(28.0, abs=0.5)
    assert "total_ml=41.0000" in end[0]


def test_shot_is_logged_once_when_routine_and_button_both_reset(
    log_dir: Path, pump: Pump, timer: BrewingTimer, flow: Flow
) -> None:
    _finish_shot(pump, timer, flow, seconds=28.0, ml=41.0)
    pump._brew_active = True

    pump.reset_brew_routine()  # button press ends the shot
    pump.reset_brew_routine()  # routine thread notices pumping stopped

    lines = [l for l in (log_dir / "shot_stat.txt").read_text().splitlines() if l.strip()]
    assert len(lines) == 1


def test_shot_stat_records_preinfusion_seconds_and_millilitres(
    log_dir: Path, pump: Pump, timer: BrewingTimer, flow: Flow
) -> None:
    _finish_shot(pump, timer, flow, seconds=28.0, ml=41.0)
    pump.preinfuse_ml = 9.5
    pump._brew_active = True

    pump.reset_brew_routine()

    line = (log_dir / "shot_stat.txt").read_text().strip()
    assert "Preinfuse s: 7.0;" in line
    assert "Preinfuse mL: 9.5;" in line


# ------------------------------------------------------------------ #
#  Brew and steam routines (run in their real threads, short timings)
# ------------------------------------------------------------------ #


def _wait_for(predicate, timeout: float = 3.0) -> bool:  # type: ignore[no-untyped-def]
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def quick_brew(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PREINFUSE_MAX_SECONDS", 0.2)
    monkeypatch.setattr(config, "BREW_DOSE_G", 20.0)
    monkeypatch.setattr(config, "BREW_TARGET_YIELD_G", 40.0)
    monkeypatch.setattr(config, "BREW_RETAINED_ML_PER_G", 1.0)  # target inlet: 40 + 20 = 60 mL
    monkeypatch.setattr(config, "BREW_BLOOM_SECONDS", 0.0)


def test_brew_stops_at_target_inlet_volume_without_a_scale(
    log_dir: Path, quick_brew: None, pump: Pump, flow: Flow
) -> None:
    pump.brew_shot()
    assert _wait_for(lambda: pump.stopped_preinfuse is not None)

    flow.total_volume = 59.0
    time.sleep(0.2)
    assert pump.pumping is True

    flow.total_volume = 60.5
    assert _wait_for(lambda: pump.pumping is False)
    pump.pump_thread.join(timeout=2)
    events = Path(shot_logger.get().event_path).read_text()  # type: ignore[union-attr]
    assert "reason=volume" in events


def test_brew_tells_the_controller_how_long_the_shot_has_left(
    log_dir: Path, quick_brew: None, pump: Pump, flow: Flow
) -> None:
    flow.get_flow_rate = lambda: 1.5  # type: ignore[assignment]
    pump.brew_shot()
    assert _wait_for(lambda: pump.stopped_preinfuse is not None)
    flow.total_volume = 30.0
    time.sleep(0.2)

    seconds = pump.temperature.set_flow_horizon.call_args.args[0]
    pump.reset_brew_routine()
    pump.pump_thread.join(timeout=2)

    # 30 mL still to go at 1.5 mL/s
    assert seconds == pytest.approx(20.0, abs=1.0)


def _in_bloom(pump: Pump) -> bool:
    return pump.pumping and pump.pwm.value == 0


def test_bloom_stops_pushing_with_the_relay_on_then_brews(
    log_dir: Path, quick_brew: None, pump: Pump, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the fill the pump stops pushing but its relay stays on, so the
    puck soaks under the fill's pressure while the heater catches up."""
    monkeypatch.setattr(config, "BREW_BLOOM_SECONDS", 0.5)
    pump.brew_shot()

    assert _wait_for(lambda: _in_bloom(pump))
    relay = [c.args[1] for c in pump.pigpio_pi.write.call_args_list if c.args[0] == config.PUMP_OUT_GPIO]
    assert relay[-1] == 1
    assert pump.stopped_preinfuse is None  # the bloom counts as preinfusion
    assert _wait_for(lambda: pump.stopped_preinfuse is not None)
    assert pump.pwm.value > 0
    assert pump.stopped_preinfuse - pump.started_preinfuse >= 0.2 + 0.5 - 0.05  # type: ignore[operator]


def test_pressing_the_button_during_the_bloom_ends_the_shot(
    log_dir: Path, quick_brew: None, pump: Pump, timer: BrewingTimer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "BREW_BLOOM_SECONDS", 5.0)
    pump.brew_shot()
    assert _wait_for(lambda: _in_bloom(pump))

    pump.brew_shot()  # the button again

    assert _wait_for(lambda: not pump.pump_thread.is_alive(), timeout=2.0)
    assert pump.pumping is False
    assert not timer.timer_running()


def test_steam_holds_steam_setpoint_until_pressed_again_without_pumping(log_dir: Path, pump: Pump) -> None:
    pump.pulse_pump_steam()

    assert _wait_for(lambda: pump.temperature.set_steam_temp.called)
    time.sleep(0.3)
    assert pump.pump_thread.is_alive()  # still steaming
    assert pump.pumping is False  # refill off by default

    pump.pulse_pump_steam()  # second press ends steaming
    assert _wait_for(lambda: not pump.pump_thread.is_alive())
    pump.temperature.set_brew_temp.assert_called_once()


def test_steam_refill_pulses_the_pump_when_enabled(
    log_dir: Path, pump: Pump, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "STEAM_REFILL_PWM", 0.4)
    pump.pulse_pump_steam()

    assert _wait_for(lambda: pump.pumping)

    pump.pulse_pump_steam()
    assert _wait_for(lambda: not pump.pump_thread.is_alive())
    assert pump.pumping is False


def test_preheat_stops_once_the_brew_head_is_ready(log_dir: Path, pump: Pump) -> None:
    ready = {"value": False}
    pump.temperature.brewhead_ready = lambda: ready["value"]
    pump.ranger.has_enough_water.return_value = True
    pump.boiler.boiling = True

    pump.pulse_pump()
    assert _wait_for(lambda: pump.pumping)
    ready["value"] = True

    assert _wait_for(lambda: not pump.pump_thread.is_alive())
    assert pump.pumping is False
