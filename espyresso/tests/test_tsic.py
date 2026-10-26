"""Tests for the TSIC ZACWire decoder: the bytes, the temperature they hold,
and what a corrupt packet does. The decoder runs on every edge (~400 a
second), so these also pin its behaviour for any faster rewrite."""

from __future__ import annotations

from typing import List
from unittest.mock import Mock

import pigpio
import pytest

from espyresso.tsic import TsicInputChannel, ZacWireInputChannel


def test_watchdog_is_switched_off_once_a_packet_has_ended() -> None:
    """pigpio repeats a watchdog timeout every period until the pin changes,
    which between readings meant ~1000 empty Python callbacks a second."""
    pi = Mock()
    pi.connected = True
    channel = ZacWireInputChannel(pi, 24)
    channel.start(Mock())
    edge = pi.callback.call_args.args[2]
    pi.set_watchdog.reset_mock()

    edge(24, pigpio.TIMEOUT, 0)

    pi.set_watchdog.assert_called_once_with(24, 0)


def _byte_bits(value: int) -> List[int]:
    """8 data bits MSB first and an even parity bit."""
    bits = [(value >> (7 - i)) & 1 for i in range(8)]
    return bits + [sum(bits) % 2]


def _bit_edges(bits: List[int], start: int) -> tuple:
    """ZACWire byte as (level, tick) edges: a 50 % strobe, then the bits;
    0-bits are mostly low, 1-bits mostly high."""
    edges, t = [(pigpio.LOW, start), (pigpio.HIGH, start + 62)], start + 125
    for bit in bits:
        edges += [(pigpio.LOW, t), (pigpio.HIGH, t + (31 if bit else 94))]
        t += 125
    return edges, t


def _byte_edges(value: int, start: int) -> tuple:
    return _bit_edges(_byte_bits(value), start)


def test_two_byte_packet_is_delivered_on_its_last_bit_without_a_watchdog(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pigpio, "tickDiff", lambda t1, t2: (t2 - t1) & 0xFFFFFFFF, raising=False)
    pi = Mock()
    pi.connected = True
    received = Mock()
    channel = ZacWireInputChannel(pi, 24)
    channel.start(received)
    edge = pi.callback.call_args.args[2]

    first, t = _byte_edges(0x03, 2000)
    second, _ = _byte_edges(0xE8, t + 200)
    for level, tick in [(pigpio.HIGH, 0)] + first + second:
        edge(24, level, tick)

    received.assert_called_once_with(ZacWireInputChannel.STATUS_OK, [0x03, 0xE8])
    assert all(c.args[1] == 0 for c in pi.set_watchdog.call_args_list)


def test_lag_between_the_packet_and_its_handling_is_measured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Python may handle edges long after they happened on a busy Pi; pigpio's
    tick says when, so the delay can be logged."""
    monkeypatch.setattr(pigpio, "tickDiff", lambda t1, t2: (t2 - t1) & 0xFFFFFFFF, raising=False)
    pi = Mock()
    pi.connected = True
    channel = ZacWireInputChannel(pi, 24)
    channel.start(Mock())
    edge = pi.callback.call_args.args[2]
    first, t = _byte_edges(0x03, 2000)
    second, end = _byte_edges(0xE8, t + 200)
    last_edge_tick = second[-1][1]
    pi.get_current_tick.return_value = last_edge_tick + 2_500_000  # handled 2.5 s late

    for level, tick in [(pigpio.HIGH, 0)] + first + second:
        edge(24, level, tick)

    assert channel.lag_ms == 2500.0


# ------------------------------------------------------------------ #
#  Bytes to °C, and corrupt packets (through TsicInputChannel)
# ------------------------------------------------------------------ #

PACKET_TICKS = 100_000  # the TSIC 306 sends 10 packets a second
GOOD = 0x5B7  # 92.94 °C


def _sensor(monkeypatch: pytest.MonkeyPatch) -> tuple:
    """A TsicInputChannel on a mock pi: its pigpio edge callback, and a mock
    that receives each Measurement."""
    monkeypatch.setattr(pigpio, "tickDiff", lambda t1, t2: (t2 - t1) & 0xFFFFFFFF, raising=False)
    pi = Mock()
    pi.connected = True
    received = Mock()
    TsicInputChannel(pi, 24).start(callback=received)
    return pi.callback.call_args.args[2], received


def _send(edge, *packets: tuple) -> None:  # type: ignore[no-untyped-def]
    """Send packets, each as (first byte's bits, second byte's bits), 100 ms apart."""
    edge(24, pigpio.HIGH, 0)
    for n, (first, second) in enumerate(packets):
        a, t = _bit_edges(first, (n + 1) * PACKET_TICKS)
        b, _ = _bit_edges(second, t + 200)
        for level, tick in a + b:
            edge(24, level, tick)


def _reading(raw: int) -> tuple:
    """A TSIC 306 packet: the top 3 of its 11 bits, then the low 8."""
    return _byte_bits(raw >> 8), _byte_bits(raw & 0xFF)


def _flip_parity(bits: List[int]) -> List[int]:
    return bits[:-1] + [1 - bits[-1]]


def _celsius(received: Mock) -> list:
    return [c.args[0].degree_celsius for c in received.call_args_list]


@pytest.mark.parametrize("raw, celsius", [(0x000, -50.0), (GOOD, 92.94), (0x7FF, 150.0)])
def test_packet_is_read_as_celsius_across_the_sensor_range(
    monkeypatch: pytest.MonkeyPatch, raw: int, celsius: float
) -> None:
    """TSIC 306 datasheet: 11 bits spread evenly over -50 to 150 °C."""
    edge, received = _sensor(monkeypatch)

    _send(edge, _reading(raw))

    assert _celsius(received) == pytest.approx([celsius], abs=0.005)


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param((_flip_parity(_byte_bits(0x05)), _byte_bits(0xB7)), id="parity_first_byte"),
        pytest.param((_byte_bits(0x05), _flip_parity(_byte_bits(0xB7))), id="parity_last_byte"),
        pytest.param((_byte_bits(0x05)[:-1], _byte_bits(0xB7)), id="bit_lost_first_byte"),
        pytest.param((_byte_bits(0x05), _byte_bits(0xB7)[:-2]), id="bits_lost_last_byte"),
        pytest.param((_byte_bits(0x05) + [0], _byte_bits(0xB7)), id="extra_bit_first_byte"),
    ],
)
def test_a_corrupt_packet_is_dropped_and_the_next_one_is_read(
    monkeypatch: pytest.MonkeyPatch, corrupt: tuple
) -> None:
    """Noise on the wire must neither become a temperature nor stop the
    readings that follow."""
    edge, received = _sensor(monkeypatch)

    _send(edge, corrupt, _reading(GOOD))

    assert _celsius(received) == pytest.approx([92.94], abs=0.005)
