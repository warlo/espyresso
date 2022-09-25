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
