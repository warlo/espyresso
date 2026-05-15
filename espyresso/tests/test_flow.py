from unittest.mock import Mock

import pytest

from espyresso import config
from espyresso.flow import Flow
from espyresso.utils import WaveQueue


@pytest.mark.parametrize(
    "input,expected",
    [
        (0.5, None),
        (0.8, 0.8488605577689243),
        (1.0, 0.6903187250996016),
        (1.7, 0.5111713147410358),
    ],
)
def test_mls_per_pulse(input: float, expected: float) -> None:

    flow_queue = WaveQueue(
        0,
        3,
        X_MIN=config.FLOW_X_MIN,
        X_MAX=config.FLOW_X_MAX,
        Y_MIN=config.FLOW_Y_MIN,
        Y_MAX=config.FLOW_Y_MAX,
        steps=5,
    )
    flow_mls = Flow(pigpio_pi=Mock(), flow_queue=flow_queue).get_mls_per_pulse(input)

    assert flow_mls == expected


# ----------------------- Flow state / behavior ------------------------ #


def _flow_queue() -> WaveQueue:
    return WaveQueue(
        0,
        3,
        X_MIN=config.FLOW_X_MIN,
        X_MAX=config.FLOW_X_MAX,
        Y_MIN=config.FLOW_Y_MIN,
        Y_MAX=config.FLOW_Y_MAX,
        steps=5,
    )


def test_flow_initial_state() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    assert flow.get_pulse_count() == 0
    assert flow.get_millilitres() == 0.0
    assert flow.first_half_period is None
    assert flow.second_half_period is None


def test_flow_get_flow_rate_with_no_pulses_is_zero() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    assert flow.get_flow_rate() == 0


def test_flow_reset_pulse_count_clears_everything() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    flow.pulse_count = 42
    flow.total_volume = 12.0
    flow.first_half_period = 0.1
    flow.second_half_period = 0.1
    flow.flow_queue.add_to_queue((1.0, 1.0))

    flow.reset_pulse_count()

    assert flow.pulse_count == 0
    assert flow.total_volume == 0.0
    assert flow.first_half_period is None
    assert flow.second_half_period is None
    assert len(flow.flow_queue) == 0


def test_flow_pulse_callback_debounces_fast_pulses() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    # Pretend we just saw a pulse moments ago
    flow.prev_change_time = float("inf")  # ensures "now" is < debounce
    # The callback uses time.perf_counter() − prev_change_time; setting
    # prev_change_time to "now" makes any subsequent call look like a bounce.
    import time

    flow.prev_change_time = time.perf_counter()
    flow.pulse_callback(0, 0, 0)
    assert flow.pulse_count == 0


def test_flow_pulse_callback_increments_count_for_valid_pulse() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    # No previous change → first pulse always passes the debounce check
    flow.pulse_callback(0, 0, 0)
    assert flow.pulse_count == 1
