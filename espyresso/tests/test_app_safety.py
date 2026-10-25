"""App wiring that keeps the heater safe across start-up, failure and stop.

pigpio and the TSIC driver are hardware and are mocked; assertions are on
what reaches the pins.
"""

from __future__ import annotations

from typing import Iterator, List
from unittest.mock import Mock, patch

import pytest

from espyresso import config, failsafe
from espyresso.tsic import Measurement


def _duties(pi: Mock, gpio: int) -> List[float]:
    return [c.args[2] for c in pi.hardware_PWM.call_args_list if c.args[0] == gpio]


# ------------------------------------------------------------------ #
#  failsafe: used by systemd before start and after stop (incl. crashes)
# ------------------------------------------------------------------ #


def test_outputs_off_zeroes_heater_and_pump_through_pigpiod() -> None:
    pi = Mock()
    pi.connected = True
    with patch.object(failsafe.pigpio, "pi", return_value=pi), patch.object(failsafe.subprocess, "run") as run:
        failsafe.outputs_off()

    assert _duties(pi, config.BOILER_PWM_GPIO) == [0]
    assert _duties(pi, config.PUMP_PWM_GPIO) == [0]
    pi.write.assert_called_with(config.PUMP_OUT_GPIO, 0)
    run.assert_not_called()


def test_outputs_off_drives_pins_low_directly_when_pigpiod_is_down() -> None:
    pi = Mock()
    pi.connected = False
    with patch.object(failsafe.pigpio, "pi", return_value=pi), patch.object(failsafe.subprocess, "run") as run:
        failsafe.outputs_off()

    commands = [c.args[0] for c in run.call_args_list]
    for gpio in (config.BOILER_PWM_GPIO, config.PUMP_OUT_GPIO, config.PUMP_PWM_GPIO):
        assert ["raspi-gpio", "set", str(gpio), "op", "dl"] in commands


# ------------------------------------------------------------------ #
#  Espyresso wiring
# ------------------------------------------------------------------ #


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:  # type: ignore[no-untyped-def]
    from espyresso import shot_logger

    monkeypatch.setattr(config, "LOG_SHOT_DIR", str(tmp_path))
    yield
    sl = shot_logger.get()
    if sl is not None:
        sl.close()
    # Plain assignment: a monkeypatch made during teardown would be undone,
    # restoring the closed logger for later tests.
    shot_logger._INSTANCE = None


@pytest.fixture
def tsic() -> Iterator[Mock]:
    with patch("espyresso.temperature.TsicInputChannel") as cls:
        cls.return_value.measure_once.return_value = Measurement(60.0, 1.0)
        yield cls.return_value


def test_control_starts_before_the_display_is_built(tsic: Mock) -> None:
    from espyresso.app import Espyresso

    started_before_display = []
    with patch("espyresso.app.Display", side_effect=lambda **kw: started_before_display.append(tsic.start.called)):
        app = Espyresso(pigpio_pi=Mock())
    app.watchdog.stop()

    assert started_before_display == [True]


def test_failed_construction_stops_control_and_heater(tsic: Mock) -> None:
    from espyresso.app import Espyresso

    pi = Mock()
    with patch("espyresso.app.Display", side_effect=RuntimeError("framebuffer missing")):
        with pytest.raises(RuntimeError):
            Espyresso(pigpio_pi=pi)

    tsic.stop.assert_called()
    assert _duties(pi, config.BOILER_PWM_GPIO)[-1] == 0


def test_stop_leaves_heater_and_pump_off(tsic: Mock) -> None:
    from espyresso.app import Espyresso

    pi = Mock()
    with patch("espyresso.app.Display"):
        app = Espyresso(pigpio_pi=pi)
    app.boiler.set_value(0.7)
    app.pump.toggle_pump()

    app.stop()

    assert _duties(pi, config.BOILER_PWM_GPIO)[-1] == 0
    pump_writes = [c.args for c in pi.write.call_args_list if c.args[0] == config.PUMP_OUT_GPIO]
    assert pump_writes[-1] == (config.PUMP_OUT_GPIO, 0)
    assert not app.watchdog.is_alive() or app.watchdog._stop_event.is_set()


def test_sighup_is_handled_before_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run directly under systemd the app is a session leader; pygame's
    framebuffer driver opens a tty, which then becomes the controlling
    terminal and sends SIGHUP during construction. The default action would
    kill the app before it reports READY."""
    import signal

    from espyresso import app as app_module

    seen = {}

    class FakeEspyresso:
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen["sighup"] = signal.getsignal(signal.SIGHUP)

        def signal_handler(self, *args: object) -> None:
            pass

        def start(self) -> None:
            pass

    saved = {s: signal.getsignal(s) for s in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    monkeypatch.setattr(config, "DEBUG", False)
    monkeypatch.setattr(app_module, "Espyresso", FakeEspyresso)
    monkeypatch.setattr(app_module, "_configure_logging", lambda: None)
    try:
        app_module.run()
    finally:
        for s, handler in saved.items():
            signal.signal(s, handler)

    assert seen["sighup"] not in (signal.SIG_DFL, None)


# ------------------------------------------------------------------ #
#  Display start-up: abandoned graphics-mode consoles and early stops
# ------------------------------------------------------------------ #


class FakeConsoles:
    """Linux VT ioctls at the OS boundary: /dev/ttyN with a KD mode each."""

    KDGETMODE, KDSETMODE = 0x4B3B, 0x4B3A

    def __init__(self, modes: dict) -> None:
        self.modes = dict(modes)  # tty number -> 0 text / 1 graphics
        self.fds: dict = {}

    def open(self, path: str, flags: int) -> int:
        n = int(path.replace("/dev/tty", ""))
        if n not in self.modes:
            raise FileNotFoundError(path)
        fd = 100 + n
        self.fds[fd] = n
        return fd

    def close(self, fd: int) -> None:
        self.fds.pop(fd, None)

    def ioctl(self, fd: int, request: int, arg: object = 0) -> object:
        import struct

        n = self.fds[fd]
        if request == self.KDGETMODE:
            return struct.pack("i", self.modes[n])
        if request == self.KDSETMODE:
            self.modes[n] = int(arg)  # type: ignore[call-overload]
            return 0
        raise OSError("unexpected ioctl")


def test_abandoned_graphics_consoles_are_reset_to_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # A killed SDL app leaves its VT in graphics mode; the kernel then ignores
    # every VT switch away from it and the next display start hangs forever.
    fake = FakeConsoles({1: 0, 2: 1, 3: 0})
    monkeypatch.setattr(failsafe.os, "open", fake.open)
    monkeypatch.setattr(failsafe.os, "close", fake.close)
    monkeypatch.setattr(failsafe.fcntl, "ioctl", fake.ioctl)

    failsafe.reset_stale_consoles()

    assert fake.modes == {1: 0, 2: 0, 3: 0}


def test_display_resets_stale_consoles_before_starting_pygame(monkeypatch: pytest.MonkeyPatch) -> None:
    from espyresso.display import Display
    from espyresso.tests.test_display import make_display

    fake = FakeConsoles({1: 0, 2: 1})
    monkeypatch.setattr(failsafe.os, "open", fake.open)
    monkeypatch.setattr(failsafe.os, "close", fake.close)
    monkeypatch.setattr(failsafe.fcntl, "ioctl", fake.ioctl)

    assert isinstance(make_display(), Display)
    assert fake.modes[2] == 0


def test_stop_signal_during_startup_exits_with_heater_off(tsic: Mock, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stop that arrives while the app is still being constructed must end
    the process promptly with the heater off (SDL would otherwise swallow
    SIGTERM and systemd falls back to SIGKILL after 90 s)."""
    import os
    import signal

    from espyresso import app as app_module

    pi = Mock()
    monkeypatch.setattr(config, "DEBUG", False)
    monkeypatch.setattr(app_module, "_configure_logging", lambda: None)
    monkeypatch.setattr(app_module.pigpio, "pi", lambda: pi)
    monkeypatch.setattr(app_module.failsafe, "outputs_off", lambda: None)
    monkeypatch.setattr(app_module, "Display", lambda **kw: os.kill(os.getpid(), signal.SIGTERM))
    saved = {s: signal.getsignal(s) for s in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    try:
        with pytest.raises(SystemExit):
            app_module.run()
    finally:
        for s, handler in saved.items():
            signal.signal(s, handler)

    tsic.stop.assert_called()
    assert _duties(pi, config.BOILER_PWM_GPIO)[-1] == 0
