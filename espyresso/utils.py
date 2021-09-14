from collections import deque

from config import ZOOM


class WaveQueue(deque):
    def __init__(
        self,
        low,
        high,
        *args,
        X_MIN,
        X_MAX,
        Y_MIN,
        Y_MAX,
        steps=10,
        target_y=None,
        **kwargs
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

        self.length = X_MAX - X_MIN
        return super().__init__(*args, **kwargs)

    def add_to_queue(self, new_value):
        popped = None
        if len(self) >= self.length / ZOOM:
            popped = self.popleft()

        self.append(new_value)

        if new_value > self.high:
            self.high = int(new_value)
        elif new_value < self.low:
            self.low = int(new_value)

        if not popped:
            return

        if int(popped) >= self.low:
            self.low = int(min(min(self), self.min_low))
        elif int(popped) >= self.high:
            self.high = int(max(max(self), self.max_high))


def linear_transform(x, a, b, c, d):
    """
    Map X within [A, B] to [C, D]
    linear_transform(70, 70, 120, 240, 50) => 240
    linear_transform(120, 70, 120, 240, 50) => 50
    """

    y = (x - a) / (b - a) * (d - c) + c
    return y
