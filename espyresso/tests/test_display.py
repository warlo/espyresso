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
    """Make a Display with mocks wired so f-string formatting works.

    The header/brew-strip renderers call ``f"{value:.0f}"`` on several
    of these returns, which fails if they're left as bare MagicMocks
    (Mock.__format__ raises TypeError on format specs)."""
    bluetooth_scale = MagicMock()
    bluetooth_scale.get_scale_weight.return_value = 0.0
    boiler = MagicMock()
    boiler.get_boiling.return_value = False
    boiler.fault = None
    boiler.pwm.get_display_value.return_value = "0.0"
    brewing_timer = MagicMock()
    brewing_timer.get_time_since_started.return_value = 0.0
    pump = MagicMock()
    pump.get_time_since_started_preinfuse.return_value = 0.0
    ranger = MagicMock()
    ranger.get_current_distance.return_value = 80.0
    flow = MagicMock()
    flow.get_millilitres.return_value = 0.0
    flow.get_flow_rate.return_value = 0.0
    return Display(
        bluetooth_scale=bluetooth_scale,
        boiler=boiler,
        buttons=MagicMock(),
        brewing_timer=brewing_timer,
        pump=pump,
        ranger=ranger,
        flow=flow,
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
    display._render("hello", 28, (255, 255, 255))
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


# ----------------------- temp legend ---------------------------------- #


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


def _spy_render(display: Display) -> list:
    """Replace display._render with a spy and return the list it
    accumulates ``(text, color)`` tuples into."""
    rendered: list = []
    original = display._render

    def spy(text, size, color):  # type: ignore[no-untyped-def]
        rendered.append((text, color))
        return original(text, size, color)

    display._render = spy  # type: ignore[assignment]
    return rendered


def test_temp_legend_renders_distinct_label_per_thermal_mass(
    display: Display,
) -> None:
    """At cold startup every thermal mass reads the same temperature;
    each label must still appear with a distinct color (the index-based
    sort was the old bug — labels are now keyed off position, not
    value)."""
    display.wave_queues["temp"] = _make_temp_queue()
    q = display.wave_queues["temp"]
    q.set_labels(["a", "b", "c", "d", "e", "f"])
    q.add_to_queue((22.0,) * 6)

    rendered = _spy_render(display)
    display._redraw_temp_legend([])

    texts = [t for t, _ in rendered]
    colors = [c for _, c in rendered]
    # First 6 labels rendered, one per thermal mass
    for label in ["a", "b", "c", "d", "e", "f"]:
        assert any(label in t for t in texts), f"missing label {label!r}"
    # Six distinct colors
    assert len(set(colors)) == 6


def test_temp_legend_renders_values_with_one_decimal(display: Display) -> None:
    display.wave_queues["temp"] = _make_temp_queue()
    q = display.wave_queues["temp"]
    q.set_labels(["shell", "elem", "water", "body", "head", "model"])
    q.add_to_queue((28.04, 50.51, 24.66, 22.7, 22.74, 23.81))

    rendered = _spy_render(display)
    display._redraw_temp_legend([])

    texts = " || ".join(t for t, _ in rendered)
    # Each value formatted to one decimal, label prefixed
    assert "shell" in texts and "28.0" in texts
    assert "elem" in texts and "50.5" in texts
    assert "water" in texts and "24.7" in texts


def test_temp_legend_skips_empty_queue(display: Display) -> None:
    display.wave_queues["temp"] = _make_temp_queue()
    # Should not raise
    display._redraw_temp_legend([])


def test_temp_legend_skips_redraw_when_values_unchanged(display: Display) -> None:
    display.wave_queues["temp"] = _make_temp_queue()
    q = display.wave_queues["temp"]
    q.set_labels(["shell", "elem", "water", "body", "head", "model"])
    q.add_to_queue((28.0, 50.5, 24.7, 22.7, 22.7, 23.8))

    dirty1: list = []
    display._redraw_temp_legend(dirty1)
    assert len(dirty1) == 1, "first frame must be dirty"

    dirty2: list = []
    display._redraw_temp_legend(dirty2)
    assert dirty2 == [], "no value changed → no dirty rect"


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


# ----------------------- partial update -------------------------------- #


def test_render_frame_returns_dirty_rects_on_first_pass(display: Display) -> None:
    """On the very first frame, every zone is "new" and should be
    reported as dirty so display.update flushes them."""
    dirty = display._render_frame()
    assert len(dirty) > 0, "first frame must report dirty zones"


def test_render_frame_skips_unchanged_zones(display: Display) -> None:
    """Second frame with identical inputs should report fewer dirty
    rects (most zones cached, only the always-changing countdown in the
    header is likely to differ — and only if a second elapsed)."""
    display._render_frame()  # warm caches
    dirty = display._render_frame()
    # No new TSIC sample, no flow data, no boiler change → all wave
    # zones should be skipped. At most the header (countdown) can be
    # dirty if a second elapsed; we just assert it's strictly fewer.
    assert len(dirty) < 8, "second frame should not redraw every zone"


def test_header_shows_fault_when_safety_switched_the_boiler_off(display: Display) -> None:
    display.boiler.fault = "sensor not responding"

    rendered = _spy_render(display)
    display._redraw_header([])

    assert any("FAULT" in t for t, _ in rendered)


def test_header_shows_off_without_a_fault(display: Display) -> None:
    rendered = _spy_render(display)
    display._redraw_header([])

    texts = [t for t, _ in rendered]
    assert any("OFF" in t for t in texts)
    assert not any("FAULT" in t for t in texts)


def test_display_loop_reports_each_frame(display: Display) -> None:
    import threading
    import time

    frames = []
    display.on_frame = lambda: frames.append(1)
    t = threading.Thread(target=display.start)
    t.start()
    deadline = time.perf_counter() + 2
    while len(frames) < 3 and time.perf_counter() < deadline:
        time.sleep(0.01)
    display.stop()
    t.join(timeout=2)

    assert len(frames) >= 3



def test_header_shows_the_brew_state(display: Display) -> None:
    from espyresso.readiness import BrewState

    display.boiler.get_boiling.return_value = True
    display.get_brew_state = lambda: BrewState.READY

    rendered = _spy_render(display)
    display._redraw_header([])

    assert ("●READY", display.GREEN) in rendered


def _run_briefly(display: Display) -> None:
    import threading
    import time

    frames = []
    display.on_frame = lambda: frames.append(1)
    t = threading.Thread(target=display.start)
    t.start()
    deadline = time.perf_counter() + 2
    while not frames and time.perf_counter() < deadline:
        time.sleep(0.01)
    display.stop()
    t.join(timeout=2)


def test_screen_says_stopped_when_the_app_stops(display: Display) -> None:
    """The screen keeps its last picture after the app or the Pi stops; a
    live-looking temperature then hid that nothing was running."""
    rendered = _spy_render(display)

    _run_briefly(display)

    last = [t for t, _ in rendered][-2:]
    assert last == ["Stopped", "heater off"]


def test_screen_says_when_it_is_safe_to_unplug_after_a_shutdown(display: Display) -> None:
    rendered = _spy_render(display)
    display.final_message = ("Shutting down", "safe to unplug in 30 s")

    _run_briefly(display)

    assert [t for t, _ in rendered][-2:] == ["Shutting down", "safe to unplug in 30 s"]
