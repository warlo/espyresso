"""Tests for ``espyresso.safety``: the raw-sensor guard and the watchdog.

These layers must hold even when the controller or its model is wrong, so
they are tested against real Boiler/Pump objects with only pigpio mocked,
asserting on what reaches the GPIO pins.
"""

from __future__ import annotations

import os
import socket
import tempfile
from typing import List
from unittest.mock import Mock

import pytest

from espyresso import config
from espyresso.boiler import Boiler
from espyresso.flow import Flow
from espyresso.pump import Pump
from espyresso.safety import SafetyGuard, Watchdog, sd_notify
from espyresso.timer import BrewingTimer
from espyresso.utils import WaveQueue

# ------------------------------------------------------------------ #
#  SafetyGuard: raw-sensor limits, independent of the model
# ------------------------------------------------------------------ #


def test_guard_passes_normal_heater_values() -> None:
    g = SafetyGuard()
    assert g.limit(now=0, temperature=94.0, heater=0.4, setpoint=95.0, flowing=False) == (0.4, "")


def test_guard_cuts_heater_above_setpoint_margin() -> None:
    g = SafetyGuard()
    heater, reason = g.limit(now=0, temperature=110.5, heater=0.4, setpoint=95.0, flowing=False)
    assert heater == 0.0
    assert reason == "overtemp"


def test_guard_overtemp_heals_when_temperature_drops() -> None:
    g = SafetyGuard()
    g.limit(now=0, temperature=111.0, heater=0.4, setpoint=95.0, flowing=False)
    assert g.limit(now=1, temperature=100.0, heater=0.4, setpoint=95.0, flowing=False) == (0.4, "")


def test_guard_absolute_cap_applies_in_steam_mode() -> None:
    g = SafetyGuard()
    heater, reason = g.limit(now=0, temperature=146.0, heater=0.8, setpoint=135.0, flowing=False)
    assert (heater, reason) == (0.0, "overtemp")


def _feed(g: SafetyGuard, temps: List[float], heater: float = 1.0, flowing: bool = False, dt: float = 1.0) -> tuple:
    result = (heater, "")
    for i, t in enumerate(temps):
        result = g.limit(now=i * dt, temperature=t, heater=heater, setpoint=95.0, flowing=flowing)
    return result


def test_guard_trips_when_full_power_does_not_raise_temperature() -> None:
    # Sensor fell off the boiler: reads room temperature while the element runs.
    heater, reason = _feed(SafetyGuard(), [23.0] * 62)
    assert heater == 0.0
    assert "sensor" in reason


def test_guard_does_not_trip_on_a_normal_cold_start() -> None:
    temps = [22.0 + 1.1 * i for i in range(66)]  # ~1 K/s, as logged
    assert _feed(SafetyGuard(), temps) == (1.0, "")


def test_guard_does_not_trip_while_water_is_flowing() -> None:
    # Flushing cold water at full power can hold the temperature flat.
    assert _feed(SafetyGuard(), [60.0] * 62, flowing=True) == (1.0, "")


def test_guard_sensor_fault_is_latched_until_cleared() -> None:
    g = SafetyGuard()
    _feed(g, [23.0] * 62)

    assert g.limit(now=100, temperature=80.0, heater=0.5, setpoint=95.0, flowing=False)[0] == 0.0
    g.clear()
    assert g.limit(now=101, temperature=80.0, heater=0.5, setpoint=95.0, flowing=False) == (0.5, "")


# ------------------------------------------------------------------ #
#  Watchdog: control heartbeat, pump on-time, auto-off, systemd
# ------------------------------------------------------------------ #


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _boiler_duties(pi: Mock) -> List[float]:
    return [c.args[2] for c in pi.hardware_PWM.call_args_list if c.args[0] == config.BOILER_PWM_GPIO]


@pytest.fixture
def rig() -> dict:
    pi = Mock()
    clock = Clock()
    started = {"t": clock.now}
    boiler = Boiler(pigpio_pi=pi, reset_started_time=Mock(), add_to_queue=Mock(), boiling=True)
    flow = Flow(pigpio_pi=pi, flow_queue=WaveQueue(0, 3, X_MIN=0, X_MAX=10, Y_MIN=0, Y_MAX=10))
    pump = Pump(
        pigpio_pi=pi,
        bluetooth_scale=Mock(),
        boiler=boiler,
        temperature=Mock(),
        flow=flow,
        reset_started_time=Mock(),
        brewing_timer=BrewingTimer(flow=flow),
        ranger=Mock(),
    )
    notify = Mock()

    def reset_started_time() -> None:
        started["t"] = clock.now

    wd = Watchdog(
        boiler=boiler,
        pump=pump,
        flow=flow,
        get_started_time=lambda: started["t"],
        reset_started_time=reset_started_time,
        notify=notify,
        clock=clock,
    )
    return dict(pi=pi, clock=clock, boiler=boiler, pump=pump, flow=flow, wd=wd, notify=notify, started=started)


def test_stale_control_forces_heater_off(rig: dict) -> None:
    rig["wd"].heartbeat()
    rig["boiler"].set_value(0.6)
    rig["clock"].now += config.CONTROL_STALE_SECONDS + 0.1

    rig["wd"].check()

    assert _boiler_duties(rig["pi"])[-1] == 0


def test_fresh_control_leaves_heater_alone(rig: dict) -> None:
    rig["boiler"].set_value(0.6)
    rig["clock"].now += 1.0
    rig["wd"].heartbeat()

    rig["wd"].check()

    assert _boiler_duties(rig["pi"])[-1] == 600000


def test_no_heartbeat_since_start_counts_as_stale(rig: dict) -> None:
    rig["boiler"].set_value(0.6)

    rig["wd"].check()

    assert _boiler_duties(rig["pi"])[-1] == 0


def test_systemd_heartbeat_only_while_control_is_fresh(rig: dict) -> None:
    rig["wd"].heartbeat()
    rig["wd"].check()
    rig["clock"].now += config.CONTROL_STALE_SECONDS + 0.1
    rig["wd"].check()

    sent = [c.args[0] for c in rig["notify"].call_args_list]
    assert sent.count("WATCHDOG=1") == 1
    assert "READY=1" in sent


def test_pump_running_too_long_is_stopped(rig: dict) -> None:
    rig["wd"].heartbeat()
    rig["pump"].toggle_pump()  # pump on
    rig["wd"].check()
    rig["clock"].now += config.PUMP_MAX_ON_SECONDS + 1
    rig["wd"].heartbeat()

    rig["wd"].check()

    assert rig["pump"].pumping is False
    pump_writes = [c.args for c in rig["pi"].write.call_args_list if c.args[0] == config.PUMP_OUT_GPIO]
    assert pump_writes[-1] == (config.PUMP_OUT_GPIO, 0)


def test_auto_off_after_idle_period(rig: dict) -> None:
    rig["clock"].now += config.TURN_OFF_SECONDS + 1
    rig["wd"].heartbeat()

    rig["wd"].check()

    assert rig["boiler"].get_boiling() is False


def test_real_water_flow_postpones_auto_off(rig: dict) -> None:
    rig["clock"].now += config.TURN_OFF_SECONDS - 60
    rig["flow"].lifetime_ml += config.AUTO_OFF_MIN_FLOW_ML + 1  # a shot pulled on the machine's switch
    rig["wd"].heartbeat()
    rig["wd"].check()
    rig["clock"].now += 120
    rig["wd"].heartbeat()

    rig["wd"].check()

    assert rig["boiler"].get_boiling() is True


def test_flow_meter_noise_does_not_postpone_auto_off(rig: dict) -> None:
    rig["clock"].now += config.TURN_OFF_SECONDS - 60
    rig["flow"].lifetime_ml += 2.0  # a few stray pulses
    rig["wd"].heartbeat()
    rig["wd"].check()
    rig["clock"].now += 120
    rig["wd"].heartbeat()

    rig["wd"].check()

    assert rig["boiler"].get_boiling() is False


def test_sd_notify_sends_to_notify_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    path = os.path.join(tempfile.mkdtemp(dir="/tmp"), "n.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(path)
    server.settimeout(1)
    monkeypatch.setenv("NOTIFY_SOCKET", path)

    sd_notify("WATCHDOG=1")

    assert server.recv(64) == b"WATCHDOG=1"
    server.close()


def test_sd_notify_without_systemd_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    sd_notify("WATCHDOG=1")


def test_control_events_distinguish_start_from_recovery(rig: dict, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from espyresso import shot_logger

    sl = shot_logger.init(str(tmp_path))
    try:
        rig["wd"].heartbeat()
        rig["wd"].check()  # first tick after start
        rig["clock"].now += config.CONTROL_STALE_SECONDS + 0.1
        rig["wd"].check()  # stalled
        rig["wd"].heartbeat()
        rig["wd"].check()  # back
    finally:
        sl.close()
        shot_logger._INSTANCE = None

    reasons = [line.split("reason=")[1].strip() for line in open(sl.event_path) if "reason=" in line]
    assert reasons == ["control_started", "control_stale", "control_resumed"]
