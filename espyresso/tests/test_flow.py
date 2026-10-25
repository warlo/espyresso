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
    assert flow.last_period is None


def test_flow_get_flow_rate_with_no_pulses_is_zero() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    assert flow.get_flow_rate() == 0


def test_flow_reset_pulse_count_clears_everything() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    flow.pulse_count = 42
    flow.total_volume = 12.0
    flow.last_period = 0.1
    flow.flow_queue.add_to_queue((1.0, 1.0))

    flow.reset_pulse_count()

    assert flow.pulse_count == 0
    assert flow.total_volume == 0.0
    assert flow.last_period is None
    assert len(flow.flow_queue) == 0


def test_flow_pulse_callback_increments_count_for_valid_pulse() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=_flow_queue())
    # No previous change → first pulse always passes the debounce check
    flow.pulse_callback(0, 0, 0)
    assert flow.pulse_count == 1


def test_lifetime_volume_keeps_counting_across_shot_resets() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=Mock())
    for i in range(6):
        flow.pulse_callback(5, 1, i * 250_000)  # 4 pulses/s
    first = flow.lifetime_ml
    flow.reset_pulse_count()  # a new shot starts
    for i in range(6):
        flow.pulse_callback(5, 1, 10_000_000 + i * 250_000)

    assert first > 0
    assert flow.get_millilitres() < flow.lifetime_ml
    assert flow.lifetime_ml > first



def _pulses(flow: Flow, count: int, hz: float, start_tick: int = 0) -> None:
    for i in range(count):
        flow.pulse_callback(5, 1, start_tick + int(i * 1e6 / hz))


def test_every_pulse_adds_its_full_volume() -> None:
    """Weighed on the machine: 64.8 g and 131.1 g of water for 140 and 284
    pulses, about 0.46 g a pulse. The code used to add half a pulse each."""
    flow = Flow(pigpio_pi=Mock(), flow_queue=Mock())

    _pulses(flow, 284, hz=12.0)

    assert flow.get_millilitres() == pytest.approx(131.1, rel=0.05)


def test_flow_rate_is_timed_from_hardware_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Edges reach Python late and in bursts when the Pi is busy; pigpio's
    tick is when the pulse actually happened."""
    import espyresso.flow as flow_module

    monkeypatch.setattr(flow_module.time, "perf_counter", lambda: 100.0)  # all handled "at once"
    flow = Flow(pigpio_pi=Mock(), flow_queue=Mock())

    _pulses(flow, 10, hz=4.0)  # 4 pulses/s, about 1.9 mL/s

    assert flow.get_flow_rate() == pytest.approx(4.0 * 0.472, rel=0.05)


def test_slow_pulses_still_count() -> None:
    flow = Flow(pigpio_pi=Mock(), flow_queue=Mock())

    _pulses(flow, 5, hz=0.4)  # slower than the calibration table goes

    assert flow.get_millilitres() > 5 * 0.45
