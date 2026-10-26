"""Tests for the Eureka Precisa: the scale process (espyresso.scale) that
talks Bluetooth, and the app side (espyresso.bluetooth) that keeps its
latest reading."""

from __future__ import annotations

import asyncio
import io
import signal
import threading
import time
from typing import Any, Iterator, List, Optional
from unittest.mock import Mock

import pytest

from espyresso import bluetooth, config, scale
from espyresso.bluetooth import BluetoothScale


def _packet(grams: float, negative: bool = False) -> bytearray:
    raw = int(round(abs(grams) * 10))
    data = bytearray(b"\xaa\x09\x41\x00\x00\x00\x00\x00\x00\x00\x41")
    data[6] = 1 if negative else 0
    data[7:9] = raw.to_bytes(2, "little")
    return data


def test_weight_is_read_in_grams() -> None:
    assert scale.grams_from(_packet(43.7)) == pytest.approx(43.7)


def test_negative_weight_keeps_its_sign() -> None:
    """Byte 6 is the sign; ignoring it read -1.0 g as +6553.5 g and stopped a
    shot on the spot."""
    assert scale.grams_from(_packet(1.0, negative=True)) == pytest.approx(-1.0)


def test_searching_backs_off_to_a_minute() -> None:
    """Searching for an asleep scale is the expensive part (BlueZ hands
    every nearby advertisement over D-Bus), so retries thin out."""
    assert [scale.retry_delay(n) for n in (1, 2, 3, 4, 5, 9)] == [10.0, 20.0, 40.0, 60.0, 60.0, 60.0]


def test_scale_process_runs_at_the_lowest_cpu_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Temperature decoding must win the Pi Zero's one core over Bluetooth."""
    nice = Mock()
    monkeypatch.setattr("espyresso.scale.os.nice", nice)
    monkeypatch.setattr("espyresso.scale.asyncio.run", lambda coro: coro.close())

    scale.main()

    nice.assert_called_once_with(19)


def test_app_reads_the_weight_the_scale_process_sends() -> None:
    s = BluetoothScale()

    s.handle_line("w 43.7")

    assert s.get_scale_weight() == pytest.approx(43.7)


def test_a_weight_older_than_five_seconds_reads_as_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr("espyresso.bluetooth.time.perf_counter", lambda: clock[0])
    s = BluetoothScale()
    s.handle_line("w 20.0")

    clock[0] += 5.5

    assert s.get_scale_weight() == 0


def test_readings_are_logged_at_most_once_a_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scale notifies several times a second; an event per reading loaded
    the Pi Zero and the SD card."""
    clock = [1000.0]
    monkeypatch.setattr("espyresso.bluetooth.time.perf_counter", lambda: clock[0])
    session = Mock()
    monkeypatch.setattr("espyresso.bluetooth.shot_logger.get", lambda: session)
    s = BluetoothScale()

    for grams in (1.0, 2.0, 3.0):
        s.handle_line(f"w {grams}")
        clock[0] += 0.2
    clock[0] += 1.0
    s.handle_line("w 4.0")
    s.handle_line("w 4.0")

    logged = [c.kwargs["grams"] for c in session.log_event.call_args_list if c.args[0] == "scale"]
    assert logged == [1.0, 4.0]


def test_connection_changes_are_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Mock()
    monkeypatch.setattr("espyresso.bluetooth.shot_logger.get", lambda: session)
    s = BluetoothScale()

    s.handle_line("link connected")
    s.handle_line("link disconnected")

    states = [c.kwargs["state"] for c in session.log_event.call_args_list if c.args[0] == "scale_link"]
    assert states == ["connected", "disconnected"]


def test_garbled_lines_are_ignored() -> None:
    s = BluetoothScale()

    for line in ("", "w", "w lots", "hello"):
        s.handle_line(line)

    assert s.get_scale_weight() == 0


class _BlockingStdout:
    """Output of a scale process that keeps running until ``event``."""

    def __init__(self, event: threading.Event) -> None:
        self.event = event

    def readline(self) -> str:
        self.event.wait()
        return ""


class _FakeProcess:
    def __init__(self, lines: List[str], stdout: Any = None) -> None:
        self.stdout = stdout if stdout is not None else io.StringIO("".join(line + "\n" for line in lines))
        self.signals: List[int] = []
        self.terminated = False

    def poll(self) -> None:
        return None

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float = 0.0) -> int:
        return 0


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(config, "DEBUG", False)
    monkeypatch.setattr(config, "BLUETOOTH_ENABLED", True)
    monkeypatch.setattr(config, "BLUETOOTH_RESTART_SECONDS", 0.05)
    yield


def _wait_for(predicate, timeout: float = 2.0) -> bool:  # type: ignore[no-untyped-def]
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_scale_process_that_dies_is_started_again(enabled: None) -> None:
    started: List[_FakeProcess] = []
    lock = threading.Lock()

    def spawn() -> _FakeProcess:
        with lock:
            p = _FakeProcess(["w 12.5"])  # one reading, then it exits
            started.append(p)
            return p

    s = BluetoothScale(spawn=spawn)
    s.start()
    try:
        assert _wait_for(lambda: len(started) >= 2)
        assert s.get_scale_weight() == pytest.approx(12.5)
    finally:
        s.stop()


def test_stop_ends_the_scale_process(enabled: None) -> None:
    blocker = threading.Event()
    process = _FakeProcess([], stdout=_BlockingStdout(blocker))
    s = BluetoothScale(spawn=lambda: process)
    s.start()
    assert _wait_for(lambda: s.process is process)

    s.stop()
    blocker.set()

    assert process.terminated


def test_request_connect_asks_the_scale_process_to_search_now(enabled: None) -> None:
    blocker = threading.Event()
    process = _FakeProcess([], stdout=_BlockingStdout(blocker))
    s = BluetoothScale(spawn=lambda: process)
    s.start()
    try:
        assert _wait_for(lambda: s.process is process)
        s.request_connect()
        assert process.signals == [signal.SIGUSR1]
    finally:
        s.stop()
        blocker.set()


def test_request_connect_before_start_is_harmless() -> None:
    BluetoothScale().request_connect()


def test_nothing_starts_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DEBUG", False)
    monkeypatch.setattr(config, "BLUETOOTH_ENABLED", False)
    spawn = Mock()

    BluetoothScale(spawn=spawn).start()

    spawn.assert_not_called()


def test_scale_process_starts_at_the_lowest_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Python's start-up and imports run before main() can lower the priority:
    at normal priority they delayed temperature decoding by 2.4 s."""
    popen = Mock()
    monkeypatch.setattr("espyresso.bluetooth.subprocess.Popen", popen)

    bluetooth._spawn_scale_process()

    assert popen.call_args.args[0][:3] == ["nice", "-n", "19"]


def test_the_scale_is_found_by_its_bluez_object_path() -> None:
    assert scale.device_path("b8:ca:04:28:79:84") == "/org/bluez/hci0/dev_B8_CA_04_28_79_84"


def test_search_waits_until_bluez_reports_the_scale() -> None:
    """BlueZ searches (in C); the scale process only asks about one device,
    instead of decoding every nearby advertisement at the lowest priority,
    which fell further behind than it could catch up."""
    answers = [None, None, -55]

    async def rssi() -> Optional[int]:
        return answers.pop(0)

    assert asyncio.run(scale.wait_until_seen(rssi, seconds=1.0, poll=0.01)) is True
    assert answers == []


def test_search_gives_up_when_the_scale_stays_away() -> None:
    async def rssi() -> Optional[int]:
        return None

    assert asyncio.run(scale.wait_until_seen(rssi, seconds=0.05, poll=0.01)) is False


def test_scale_process_dies_with_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """An old scale process, too busy catching up to run its own exit, kept
    running for 19 minutes after the app restarted and starved temperature
    decoding by 44 s. The kernel now kills it with the app."""
    die = Mock()
    monkeypatch.setattr("espyresso.scale.os.nice", Mock())
    monkeypatch.setattr("espyresso.scale.die_with_parent", die)
    monkeypatch.setattr("espyresso.scale.asyncio.run", lambda coro: coro.close())

    scale.main()

    die.assert_called_once_with()
