"""Tests for the TSIC ZACWire decoder's use of the pigpio watchdog."""

from __future__ import annotations

from unittest.mock import Mock

import pigpio

from espyresso.tsic import ZacWireInputChannel


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


def _byte_edges(value: int, start: int) -> tuple:
    """ZACWire byte as (level, tick) edges: a 50 % strobe, 8 data bits MSB
    first and an even parity bit; 0-bits are mostly low, 1-bits mostly high."""
    bits = [(value >> (7 - i)) & 1 for i in range(8)]
    bits.append(sum(bits) % 2)
    edges, t = [(pigpio.LOW, start), (pigpio.HIGH, start + 62)], start + 125
    for bit in bits:
        edges += [(pigpio.LOW, t), (pigpio.HIGH, t + (31 if bit else 94))]
        t += 125
    return edges, t


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
