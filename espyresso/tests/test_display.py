"""Tests for ``espyresso.display``.

pygame is mocked in ``conftest.py`` so these tests can run anywhere. We
cover:

  * the render cache: same key → same Surface; LRU eviction at capacity
  * the hline cache: one alpha surface per width
  * ``draw_degrees`` with duplicate temperature values — the existing
    code calls ``degrees.index(degree)`` which returns the *first*
    matching index, collapsing all duplicates to the same label/color.
    The test below asserts the desired post-fix behavior, so it FAILS
    until the bug is fixed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from espyresso import config
from espyresso.display import Display, _RENDER_CACHE_MAX
from espyresso.utils import WaveQueue


def make_display() -> Display:
    return Display(
        bluetooth_scale=MagicMock(),
        boiler=MagicMock(),
        buttons=MagicMock(),
        brewing_timer=MagicMock(),
        pump=MagicMock(),
        ranger=MagicMock(),
        flow=MagicMock(),
        get_started_time=lambda: 0.0,
        wave_queues={},
    )


@pytest.fixture
def display() -> Display:
    return make_display()


# ----------------------- render cache --------------------------------- #


def test_render_cache_returns_same_surface_for_same_key(display: Display) -> None:
    a = display._render("hello", 12, (255, 255, 255))
    b = display._render("hello", 12, (255, 255, 255))
    assert a is b


def test_render_cache_distinct_keys_distinct_entries(display: Display) -> None:
    """Different (text, size, color) tuples must occupy separate cache slots.
    (We assert on the cache dict — pygame.font.Font.render is mocked so all
    rendered Surfaces share identity.)"""
    display._render("hello", 12, (255, 255, 255))
    display._render("world", 12, (255, 255, 255))
    display._render("hello", 42, (255, 255, 255))
    display._render("hello", 12, (255, 0, 0))
    assert len(display._render_cache) == 4


def test_render_cache_calls_font_render_only_once_per_key(display: Display) -> None:
    font12 = display._fonts[12]
    font12.render.reset_mock()
    display._render("repeat", 12, (255, 255, 255))
    display._render("repeat", 12, (255, 255, 255))
    display._render("repeat", 12, (255, 255, 255))
    assert font12.render.call_count == 1


def test_render_cache_evicts_lru_at_capacity(display: Display) -> None:
    # Populate beyond the cap with N+1 distinct entries; oldest must be evicted.
    for i in range(_RENDER_CACHE_MAX + 1):
        display._render(str(i), 12, (255, 255, 255))
    assert len(display._render_cache) == _RENDER_CACHE_MAX
    # Entry 0 was the first inserted and never re-accessed → evicted.
    assert ("0", 12, (255, 255, 255)) not in display._render_cache
    # The most recent entry must still be present.
    assert (str(_RENDER_CACHE_MAX), 12, (255, 255, 255)) in display._render_cache


def test_render_cache_lru_promotion_keeps_hot_entries(display: Display) -> None:
    """Touching an entry must promote it past older ones so subsequent
    evictions hit the older entries first.

    Insertion plan:  1 ("hot") + N/2 x-entries + touch-hot + N/2 y-entries
                  =  1 + 256 + 256  = 513 total inserts
                  → exactly 1 eviction (cap is 512). With the LRU
                    promotion working, that eviction must hit x0,
                    NOT hot.
    """
    half = _RENDER_CACHE_MAX // 2
    display._render("hot", 12, (255, 255, 255))
    for i in range(half):
        display._render(f"x{i}", 12, (255, 255, 255))
    display._render("hot", 12, (255, 255, 255))  # promote to most-recent
    for i in range(half):
        display._render(f"y{i}", 12, (255, 255, 255))
    assert len(display._render_cache) == _RENDER_CACHE_MAX
    assert ("hot", 12, (255, 255, 255)) in display._render_cache
    assert ("x0", 12, (255, 255, 255)) not in display._render_cache


# ----------------------- hline cache ---------------------------------- #


def test_hline_cache_returns_same_surface_for_same_width(display: Display) -> None:
    a = display._get_hline(132)
    b = display._get_hline(132)
    assert a is b


def test_hline_cache_distinct_widths_distinct_entries(display: Display) -> None:
    display._get_hline(132)
    display._get_hline(160)
    assert set(display._hline_cache.keys()) == {132, 160}


def test_hline_cache_does_not_re_create_for_known_width(display: Display) -> None:
    import pygame  # mocked in conftest

    pygame.Surface.reset_mock()  # type: ignore[attr-defined]
    display._get_hline(132)
    display._get_hline(132)
    display._get_hline(132)
    assert pygame.Surface.call_count == 1  # type: ignore[attr-defined]


# ----------------------- draw_degrees bug ----------------------------- #


def _make_temp_queue() -> WaveQueue:
    q = WaveQueue(
        90,
        100,
        X_MIN=config.TEMP_X_MIN,
        X_MAX=config.TEMP_X_MAX,
        Y_MIN=config.TEMP_Y_MIN,
        Y_MAX=config.TEMP_Y_MAX,
        target_y=config.TARGET_TEMP,
    )
    return q


def test_draw_degrees_renders_distinct_label_per_thermal_mass(
    display: Display,
) -> None:
    """Regression: at cold startup every thermal mass reads the same
    temperature; the labels must still appear with distinct names and
    distinct colors. Currently FAILS because ``degrees.index(degree)``
    returns 0 for every duplicate."""
    q = _make_temp_queue()
    q.set_labels(["A", "B", "C"])
    q.add_to_queue((22.0, 22.0, 22.0))

    rendered_args: list = []
    original_render = display._render

    def spy(text: str, size: int, color):  # type: ignore[no-untyped-def]
        rendered_args.append((text, color))
        return original_render(text, size, color)

    display._render = spy  # type: ignore[assignment]

    display.draw_degrees(q)

    texts = [t for t, _ in rendered_args]
    colors = [c for _, c in rendered_args]

    assert "A: 22.0°C" in texts
    assert "B: 22.0°C" in texts
    assert "C: 22.0°C" in texts
    # All three should have distinct colors (one per series)
    assert len(set(colors)) == 3


def test_draw_degrees_handles_unique_values(display: Display) -> None:
    """Sanity check — when temperatures are all distinct, the existing
    code already works. This test should pass before and after the
    duplicate-handling fix."""
    q = _make_temp_queue()
    q.set_labels(["A", "B", "C"])
    q.add_to_queue((22.0, 50.0, 95.0))

    rendered = []
    original_render = display._render

    def spy(text, size, color):  # type: ignore[no-untyped-def]
        rendered.append(text)
        return original_render(text, size, color)

    display._render = spy  # type: ignore[assignment]
    display.draw_degrees(q)

    assert "A: 22.0°C" in rendered
    assert "B: 50.0°C" in rendered
    assert "C: 95.0°C" in rendered


def test_draw_degrees_skips_empty_queue(display: Display) -> None:
    """Defensive: don't crash on an empty queue."""
    q = _make_temp_queue()  # never .add_to_queue()'d
    # Should not raise
    display.draw_degrees(q)


# ----------------------- draw_coordinates ----------------------------- #


def test_draw_coordinates_calls_draw_lines_once_per_series(display: Display) -> None:
    """One pygame.draw.lines call per series, not one draw.line per segment.

    Currently FAILS because draw_coordinates uses ``pygame.draw.line``
    (singular) in a Python-level segment loop — ~66 round trips per
    series instead of 1."""
    import pygame  # mocked in conftest

    q = _make_temp_queue()
    q.add_to_queue((22.0, 50.0, 95.0))
    q.add_to_queue((23.0, 51.0, 96.0))
    q.add_to_queue((24.0, 52.0, 97.0))

    pygame.draw.lines.reset_mock()  # type: ignore[attr-defined]
    display.draw_coordinates(q, q.X_MIN, q.X_MAX, q.Y_MIN, q.Y_MAX, q.low, q.high)
    # 3 series → 3 draw.lines calls
    assert pygame.draw.lines.call_count == 3  # type: ignore[attr-defined]


def test_draw_coordinates_empty_queue_does_not_crash(display: Display) -> None:
    q = _make_temp_queue()
    display.draw_coordinates(q, q.X_MIN, q.X_MAX, q.Y_MIN, q.Y_MAX, q.low, q.high)
