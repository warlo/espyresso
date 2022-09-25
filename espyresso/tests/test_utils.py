from espyresso import config
from espyresso.utils import WaveQueue


def test_queue_lower_than_min() -> None:

    temp_queue = WaveQueue(
        90,
        100,
        X_MIN=config.TEMP_X_MIN,
        X_MAX=config.TEMP_X_MAX,
        Y_MIN=config.TEMP_Y_MIN,
        Y_MAX=config.TEMP_Y_MAX,
        target_y=config.TARGET_TEMP,
    )
    temp_queue.add_to_queue(tuple((80.0,)))

    assert temp_queue.low == 80.0
    assert temp_queue.high == 100.0


def test_queue_higher_than_max() -> None:

    temp_queue = WaveQueue(
        90,
        100,
        X_MIN=config.TEMP_X_MIN,
        X_MAX=config.TEMP_X_MAX,
        Y_MIN=config.TEMP_Y_MIN,
        Y_MAX=config.TEMP_Y_MAX,
        target_y=config.TARGET_TEMP,
    )
    temp_queue.add_to_queue(tuple((120.0,)))

    assert temp_queue.low == 90.0
    assert temp_queue.high == 120.0


def test_queue_popping_highest() -> None:

    temp_queue = WaveQueue(
        90,
        100,
        X_MIN=config.TEMP_X_MIN,
        X_MAX=config.TEMP_X_MAX,
        Y_MIN=config.TEMP_Y_MIN,
        Y_MAX=config.TEMP_Y_MAX,
        target_y=config.TARGET_TEMP,
    )
    assert temp_queue.length == 132

    temp_queue.add_to_queue(tuple((110.0,)))
    for i in range(65):
        temp_queue.add_to_queue(tuple((65,)))

    assert len(temp_queue) == 66
    assert temp_queue.high == 110.0

    temp_queue.add_to_queue(tuple((105.0,)))
    assert temp_queue.high == 105.0
