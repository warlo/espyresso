"""Tests for the Eureka Precisa notification handling in espyresso.bluetooth."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from espyresso import bluetooth
from espyresso.bluetooth import BluetoothScale


def _packet(grams: float, negative: bool = False) -> bytearray:
    raw = int(round(abs(grams) * 10))
    data = bytearray(b"\xaa\x09\x41\x00\x00\x00\x00\x00\x00\x00\x41")
    data[6] = 1 if negative else 0
    data[7:9] = raw.to_bytes(2, "little")
    return data


def test_weight_is_read_in_grams() -> None:
    scale = BluetoothScale()

    scale.callback(0, _packet(43.7))

    assert scale.get_scale_weight() == pytest.approx(43.7)


def test_negative_weight_keeps_its_sign() -> None:
    """Byte 6 is the sign; ignoring it read -1.0 g as +6553.5 g and stopped a
    shot on the spot."""
    scale = BluetoothScale()

    scale.callback(0, _packet(1.0, negative=True))

    assert scale.get_scale_weight() == pytest.approx(-1.0)


def test_readings_are_logged_at_most_once_a_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scale notifies several times a second; an event per reading loaded
    the Pi Zero and the SD card."""
    clock = [1000.0]
    monkeypatch.setattr(bluetooth.time, "perf_counter", lambda: clock[0])
    session = Mock()
    monkeypatch.setattr(bluetooth.shot_logger, "get", lambda: session)
    scale = BluetoothScale()

    for grams in (1.0, 2.0, 3.0):
        scale.callback(0, _packet(grams))
        clock[0] += 0.2
    clock[0] += 1.0
    scale.callback(0, _packet(4.0))
    scale.callback(0, _packet(4.0))

    assert [c.kwargs["grams"] for c in session.log_event.call_args_list] == [1.0, 4.0]
