import pytest

from espyresso import config
from espyresso.utils import WaveQueue, linear_transform


# ----------------------- linear_transform ----------------------------- #


def test_linear_transform_endpoints() -> None:
    assert linear_transform(70, 70, 120, 240, 50) == 240
    assert linear_transform(120, 70, 120, 240, 50) == 50


def test_linear_transform_midpoint() -> None:
    assert linear_transform(95, 70, 120, 240, 50) == pytest.approx(145.0)


def test_linear_transform_outside_range_extrapolates() -> None:
    # function is a pure linear map and does not clamp
    out = linear_transform(50, 70, 120, 240, 50)
    assert out > 240


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


# ----------------------- WaveQueue edge cases ------------------------- #


def _temp_queue() -> WaveQueue:
    return WaveQueue(
        90,
        100,
        X_MIN=config.TEMP_X_MIN,
        X_MAX=config.TEMP_X_MAX,
        Y_MIN=config.TEMP_Y_MIN,
        Y_MAX=config.TEMP_Y_MAX,
        target_y=config.TARGET_TEMP,
    )


def test_queue_set_labels() -> None:
    q = _temp_queue()
    q.set_labels(["a", "b", "c"])
    assert q.queue_labels == ["a", "b", "c"]


def test_queue_within_bounds_does_not_extend_range() -> None:
    q = _temp_queue()
    q.add_to_queue((95.0,))
    assert q.low == 90
    assert q.high == 100


def test_queue_duplicate_values_track_min_max_correctly() -> None:
    q = _temp_queue()
    q.add_to_queue((85.0,))
    q.add_to_queue((85.0,))
    q.add_to_queue((85.0,))
    assert q.low == 85
    assert q.high == 100


def test_queue_get_min_max_methods() -> None:
    q = _temp_queue()
    q.add_to_queue((80.0,))
    q.add_to_queue((110.0,))
    # get_min/get_max consider the seed low/high too
    assert q.get_min() == 80
    assert q.get_max() == 110
