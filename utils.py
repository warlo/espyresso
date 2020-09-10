def linear_transform(x, a, b, c, d):
    """
    Map X within [A, B] to [C, D]
    linear_transform(70, 70, 120, 240, 50) => 240
    linear_transform(120, 70, 120, 240, 50) => 50
    """

    y = (x - a) / (b - a) * (d - c) + c
    return y