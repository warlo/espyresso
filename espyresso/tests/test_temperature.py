"""Tests for ``espyresso.temperature.Temperature``: the control tick.

The TSIC driver is external hardware, so it is patched; the controller,
safety guard and boiler are real, and assertions are made on the duty
cycle that reaches the boiler's PWM pin (pigpio mocked).
"""

from __future__ import annotations

import types
from typing import Iterator, List
from unittest.mock import Mock, patch

import pytest

from espyresso import config
from espyresso import pcontroller as pcm
from espyresso import temperature as temperature_module
from espyresso.boiler import Boiler
from espyresso.temperature import Temperature
from espyresso.tsic import Measurement
from espyresso.utils import WaveQueue


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    fake = types.SimpleNamespace(perf_counter=lambda: c.now)
    monkeypatch.setattr(pcm, "time", fake)
    monkeypatch.setattr(temperature_module, "time", fake)
    return c


def _duties(pi: Mock) -> List[float]:
    return [c.args[2] / 1e6 for c in pi.hardware_PWM.call_args_list if c.args[0] == config.BOILER_PWM_GPIO]


class Rig:
    def __init__(self, first_reading: Measurement, clock: Clock) -> None:
        self.clock = clock
        self.pi = Mock()
        self.boiler = Boiler(pigpio_pi=self.pi, reset_started_time=Mock(), add_to_queue=Mock(), boiling=True)
        self.flow = Mock()
        self.flow.get_flow_rate.return_value = 0.0
        self.flow.get_millilitres.return_value = 0.0
        self.heartbeat = Mock()
        with patch("espyresso.temperature.TsicInputChannel") as tsic_cls:
            tsic_cls.return_value.measure_once.return_value = first_reading
            self.tsic = tsic_cls.return_value
            self.temperature = Temperature(
                pigpio_pi=self.pi,
                boiler=self.boiler,
                flow=self.flow,
                get_started_time=lambda: clock.now,
                temp_queue=WaveQueue(90, 100, X_MIN=0, X_MAX=10, Y_MIN=0, Y_MAX=10),
                heartbeat=self.heartbeat,
            )

    def tick(self, celsius: float, seconds: float = 0.1) -> float:
        self.clock.now += seconds
        self.temperature.callback(Measurement(celsius, self.clock.now))
        return _duties(self.pi)[-1]


@pytest.fixture
def rig_factory(clock: Clock) -> Iterator:
    yield lambda first: Rig(first, clock)


def test_failed_first_reading_does_not_start_the_model_cold(rig_factory) -> None:
    rig = rig_factory(Measurement.UNDEF)
    hot = config.TARGET_TEMP + 0.5

    duty = rig.tick(hot)

    # A model initialised at the 22 C fallback would demand full power here.
    assert duty < 0.5
    assert rig.temperature.pcontroller.waterTemp == pytest.approx(hot, abs=1.0)


def test_boot_boost_starts_on_first_valid_reading_when_below_setpoint(rig_factory) -> None:
    # 1.5 K below setpoint the controller alone asks for ~0.6; the boost
    # (0.67 s) runs the first tick at full power.
    near = config.TARGET_TEMP - 1.5
    rig = rig_factory(Measurement(near, 999.0))
    assert rig.tick(near, seconds=6.0) == 1.0


def test_no_boot_boost_when_already_hot(rig_factory) -> None:
    hot = config.TARGET_TEMP + 1.0
    rig = rig_factory(Measurement(hot, 999.0))
    assert rig.tick(hot, seconds=6.0) < 1.0


def test_detached_sensor_switches_boiler_off(rig_factory) -> None:
    rig = rig_factory(Measurement(23.0, 999.0))
    duty = 1.0
    for _ in range(int((config.SAFETY_RUNAWAY_SECONDS + 2) / 0.1)):
        duty = rig.tick(23.0)  # element on, sensor never moves

    assert duty == 0.0
    assert rig.boiler.get_boiling() is False
    assert rig.boiler.fault == "sensor not responding"


def test_exception_in_control_tick_turns_heater_off(rig_factory) -> None:
    rig = rig_factory(Measurement(60.0, 999.0))
    rig.tick(60.0, seconds=6.0)  # cold: heating
    rig.flow.get_flow_rate.side_effect = RuntimeError("flow meter state broke")

    duty = rig.tick(60.0)

    assert duty == 0.0


def test_heartbeat_only_after_a_completed_tick(rig_factory) -> None:
    rig = rig_factory(Measurement(60.0, 999.0))

    rig.temperature.callback(Measurement(None, None))
    assert rig.heartbeat.call_count == 0

    rig.tick(60.0)
    assert rig.heartbeat.call_count == 1


def test_stop_leaves_pwm_at_zero_even_after_boiler_flag_cleared(rig_factory) -> None:
    rig = rig_factory(Measurement(60.0, 999.0))
    rig.tick(60.0, seconds=6.0)
    rig.boiler.boiling = False  # e.g. turned off while a tick was in flight

    rig.temperature.stop()

    assert _duties(rig.pi)[-1] == 0.0
    rig.tsic.stop.assert_called_once()


@pytest.mark.parametrize("setpoint,head,ready", [(95.0, 81.0, True), (95.0, 79.0, False), (99.0, 81.0, False), (99.0, 85.0, True)])
def test_brew_head_readiness_follows_the_setpoint(rig_factory, setpoint: float, head: float, ready: bool) -> None:
    rig = rig_factory(Measurement(95.0, 999.0))
    rig.temperature.pcontroller.set_target_temp(setpoint)
    rig.temperature.pcontroller.brewHeadTemp = head

    assert rig.temperature.brewhead_ready() is ready


# ------------------------------------------------------------------ #
#  What the control tick leaves behind for analysis
# ------------------------------------------------------------------ #


@pytest.fixture
def session(tmp_path):  # type: ignore[no-untyped-def]
    from espyresso import shot_logger

    sl = shot_logger.init(str(tmp_path))
    yield sl
    sl.close()
    shot_logger._INSTANCE = None


def _rows(path: str) -> List[dict]:
    import csv

    with open(path) as f:
        return list(csv.DictReader(f))


def test_control_tick_logs_a_row_with_the_analysis_columns(rig_factory, session) -> None:  # type: ignore[no-untyped-def]
    rig = rig_factory(Measurement(60.0, 999.0))
    rig.tick(60.0, seconds=6.0)
    rig.tick(60.5)
    session.close()

    rows = _rows(session.tick_path)
    assert [float(r["raw_temp"]) for r in rows] == [60.0, 60.5]
    for column in ("heater", "heater_cmd", "safety", "boost", "resync", "flow_horizon_s", "waterTemp", "setpoint"):
        assert column in rows[0]
    assert rows[0]["boost"] == "1"  # cold: boot boost on the first tick
    assert rows[0]["resync"] == "gap"  # slow first step re-synced the model


def test_safety_fault_is_logged_as_an_event(rig_factory, session) -> None:  # type: ignore[no-untyped-def]
    rig = rig_factory(Measurement(23.0, 999.0))
    for _ in range(int((config.SAFETY_RUNAWAY_SECONDS + 2) / 0.1)):
        rig.tick(23.0)
    session.close()

    events = open(session.event_path).read()
    assert "safety,reason=sensor not responding" in events


def test_switching_boiler_on_after_a_fault_resumes_heating(rig_factory) -> None:  # type: ignore[no-untyped-def]
    rig = rig_factory(Measurement(23.0, 999.0))
    for _ in range(int((config.SAFETY_RUNAWAY_SECONDS + 2) / 0.1)):
        rig.tick(23.0)
    assert rig.boiler.get_boiling() is False

    rig.boiler.toggle_boiler()  # user acknowledges and switches on again

    assert rig.tick(23.5) == 1.0
    assert rig.boiler.fault is None
