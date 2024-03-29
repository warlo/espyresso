import math
from collections import deque
from typing import Any, List, Optional, Tuple, Union

from espyresso.config import ZOOM


class WaveQueue(deque):  # type: ignore
    def __init__(
        self,
        low: int,
        high: int,
        *args: Any,
        X_MIN: int,
        X_MAX: int,
        Y_MIN: int,
        Y_MAX: int,
        steps: int = 10,
        target_y: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        self.low = low
        self.high = high
        self.min_low = low
        self.max_high = high
        self.steps = steps
        self.target_y = target_y
        self.X_MIN = X_MIN
        self.X_MAX = X_MAX
        self.Y_MIN = Y_MIN
        self.Y_MAX = Y_MAX
        self.queue_labels: List[str] = []

        self.length = X_MAX - X_MIN
        return super().__init__(*args, **kwargs)

    def set_labels(self, labels: List[str]) -> None:
        self.queue_labels = labels

    def get_min(self) -> int:
        min_val: Union[int, float] = self.high
        for val in self:
            new_min = min(val)
            if new_min < min_val:
                min_val = new_min
        return int(min(min_val, self.min_low))

    def get_max(self) -> int:
        max_val: Union[int, float] = self.low
        for val in self:
            new_max = max(val)
            if new_max > max_val:
                max_val = new_max
        return math.ceil(max(max_val, self.max_high))

    def add_to_queue(self, new_value: Tuple[float, ...]) -> None:
        popped = None
        if len(self) >= self.length / ZOOM:
            popped = self.popleft()

        self.append(new_value)

        new_high = max(new_value)
        new_low = min(new_value)
        if new_high > self.high:
            self.high = int(math.ceil(new_high))
        elif new_low < self.low:
            self.low = int(new_low)

        if not popped:
            return

        if int(min(popped)) <= self.low:
            self.low = self.get_min()

        if math.ceil(max(popped)) >= self.high:
            self.high = self.get_max()
        # self.high = int(self.get_max())


def linear_transform(x: float, a: float, b: float, c: float, d: float) -> float:
    """
    Map X within [A, B] to [C, D]
    linear_transform(70, 70, 120, 240, 50) => 240
    linear_transform(120, 70, 120, 240, 50) => 50
    """

    y = (x - a) / (b - a) * (d - c) + c
    return y
