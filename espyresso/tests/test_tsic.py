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
