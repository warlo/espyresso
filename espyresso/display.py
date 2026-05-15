import logging
import os
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import pygame

from espyresso import config

# Cap on cached rendered-text surfaces. Each entry is a tiny SDL surface
# (a few KB at most for the fonts used here). 512 entries covers all
# static labels plus a wide range of dynamic values (timer ticks, etc.)
# with comfortable headroom; LRU eviction handles overflow.
_RENDER_CACHE_MAX = 512

if TYPE_CHECKING:
    from espyresso.boiler import Boiler
    from espyresso.flow import Flow
    from espyresso.pump import Pump
    from espyresso.ranger import Ranger
    from espyresso.timer import BrewingTimer
    from espyresso.bluetooth import BluetoothScale
    from espyresso.buttons import Buttons

from espyresso.utils import WaveQueue, linear_transform

logger = logging.getLogger(__name__)


class Display:
    # Colors (class-level — never change at runtime)
    BLACK = (0, 0, 0)
    GREY = (100, 100, 100)
    WHITE = (255, 255, 255)
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    LIGHT_BLUE = (0, 255, 255)
    BLUE = (0, 0, 255)
    ORANGE = (255, 140, 0)
    YELLOW = (255, 255, 0)
    PINK = (255, 0, 255)

    def __init__(
        self,
        *args: Any,
        bluetooth_scale: "BluetoothScale",
        boiler: "Boiler",
        buttons: "Buttons",
        brewing_timer: "BrewingTimer",
        pump: "Pump",
        ranger: "Ranger",
        flow: "Flow",
        get_started_time: Callable[[], float],
        wave_queues: Dict[str, WaveQueue],
        **kwargs: Any,
    ) -> None:
        os.environ["SDL_FBDEV"] = "/dev/fb1"
        # Uncomment if you have a touch panel and find the X value for your device
        # os.environ["SDL_MOUSEDRV"] = "TSLIB"
        # os.environ["SDL_MOUSEDEV"] = "/dev/input/eventX"

        pygame.display.init()
        pygame.mouse.set_visible(False)
        pygame.font.init()

        pygame.event.set_allowed(None)
        if not config.DEBUG:
            flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
        else:
            flags = pygame.HWSURFACE | pygame.DOUBLEBUF
        self.screen = pygame.display.set_mode((config.WIDTH, config.HEIGHT), flags)

        font = str(Path(__file__).parent / "nk57-monospace-cd-rg.ttf")
        self.big_font = pygame.font.Font(font, 28)
        self.medium_font = pygame.font.Font(font, 18)
        self.small_font = pygame.font.Font(font, 12)

        # Render cache: pygame.font.Font.render() allocates a new SDL surface
        # per call. Cache by (text, font_size, color) with LRU eviction so
        # static labels and most dynamic values become zero-allocation blits
        # after the first render.
        self._fonts: Dict[int, pygame.font.Font] = {
            28: self.big_font,
            18: self.medium_font,
            12: self.small_font,
        }
        self._render_cache: "OrderedDict[Tuple[str, int, Tuple[int, int, int]], pygame.Surface]" = OrderedDict()

        # Pre-rendered translucent horizontal grid line, keyed by width.
        self._hline_cache: Dict[int, pygame.Surface] = {}

        # Series colors for the temp waveform (one per thermal mass, in
        # the order PController.update returns).
        self.colors = [
            self.GREEN,
            self.ORANGE,
            self.LIGHT_BLUE,
            self.BLUE,
            self.WHITE,
            self.PINK,
            self.YELLOW,
        ]

        # Layout rects (turn config tuples into pygame.Rect once)
        self.rect_header = pygame.Rect(*config.LAYOUT_HEADER)
        self.rect_brew = pygame.Rect(*config.LAYOUT_BREW)
        self.rect_temp_legend = pygame.Rect(*config.LAYOUT_TEMP_LEGEND)
        self.rect_temp_wave = pygame.Rect(*config.LAYOUT_TEMP_WAVE)
        self.rect_flow_header = pygame.Rect(*config.LAYOUT_FLOW_HEADER)
        self.rect_flow_wave = pygame.Rect(*config.LAYOUT_FLOW_WAVE)
        self.rect_boiler_header = pygame.Rect(*config.LAYOUT_BOILER_HEADER)
        self.rect_boiler_wave = pygame.Rect(*config.LAYOUT_BOILER_WAVE)

        # Dirty-tracking state. Each zone records whatever value last
        # produced its rendered output; if the new value matches, we
        # skip the redraw and don't add the rect to display.update().
        self._last_header: Optional[str] = None
        self._last_brew: Optional[str] = None
        self._last_legend: Optional[Tuple[Any, ...]] = None
        self._last_flow_header: Optional[str] = None
        self._last_flow_wave_token: Any = None
        self._last_boiler_header: Optional[str] = None
        self._last_boiler_wave_token: Any = None
        self._last_temp_wave_token: Any = None

        self.boiler = boiler
        self.buttons = buttons
        self.brewing_timer = brewing_timer
        self.pump = pump
        self.ranger = ranger
        self.flow = flow
        self.get_started_time = get_started_time
        self.bluetooth_scale = bluetooth_scale

        self._stop_event = threading.Event()
        self.wave_queues = wave_queues

    # ------------------------------------------------------------------ #
    #  Caching helpers
    # ------------------------------------------------------------------ #

    def _render(
        self,
        text: str,
        size: int,
        color: Tuple[int, int, int],
    ) -> pygame.Surface:
        """Return a cached rendered Surface for (text, font size, color)."""
        key = (text, size, color)
        cached = self._render_cache.get(key)
        if cached is not None:
            self._render_cache.move_to_end(key)
            return cached
        surf = self._fonts[size].render(text, True, color)
        self._render_cache[key] = surf
        if len(self._render_cache) > _RENDER_CACHE_MAX:
            self._render_cache.popitem(last=False)
        return surf

    def _get_hline(self, width: int) -> pygame.Surface:
        surf = self._hline_cache.get(width)
        if surf is None:
            surf = pygame.Surface((width, 1), flags=pygame.SRCALPHA)
            surf.fill((255, 255, 255, 100))
            self._hline_cache[width] = surf
        return surf

    # ------------------------------------------------------------------ #
    #  Waveform primitives (unchanged math, just cleaner names)
    # ------------------------------------------------------------------ #

    @staticmethod
    def generate_coordinate(
        *,
        index: int,
        value: float,
        low: int,
        high: int,
        Y_MIN: int,
        Y_MAX: int,
    ) -> Tuple[int, float]:
        return (index, round(linear_transform(value, low, high, Y_MAX, Y_MIN)))

    def generate_coordinates(
        self,
        values: Any,
        X_MIN: int,
        X_MAX: int,
        Y_MIN: int,
        Y_MAX: int,
        low: int,
        high: int,
    ) -> List[Tuple[int, float]]:
        return [
            self.generate_coordinate(
                index=X_MIN + index * config.ZOOM,
                value=value,
                low=low,
                high=high,
                Y_MIN=Y_MIN,
                Y_MAX=Y_MAX,
            )
            for index, value in enumerate(values)
        ]

    def draw_y_axis(
        self,
        X_MIN: int,
        X_MAX: int,
        Y_MIN: int,
        Y_MAX: int,
        low: int,
        high: int,
        number_of_steps: int,
    ) -> None:
        pygame.draw.line(self.screen, self.WHITE, (X_MIN, Y_MAX), (X_MIN, Y_MIN))
        pygame.draw.line(self.screen, self.WHITE, (X_MIN, Y_MAX), (X_MAX, Y_MAX))

        range_steps = int(high - low) or 1
        steps: List[Tuple[float, int]] = []
        rounded = True
        for i in range(low * number_of_steps, high * number_of_steps, range_steps):
            closest_step = i / number_of_steps
            y_val = round(linear_transform(closest_step, low, high, Y_MAX, Y_MIN))
            if y_val < Y_MIN:
                continue
            steps.append((closest_step, y_val))
            if not closest_step.is_integer():
                rounded = False

        hline = self._get_hline(X_MAX - X_MIN)
        for (step, y_val) in steps:
            if rounded:
                step = round(step)
            label = self._render(str(step), 12, self.WHITE)
            self.screen.blit(label, (X_MIN - 24, y_val - 8))
            self.screen.blit(hline, (X_MIN, y_val))

    def draw_target_line(
        self,
        target: float,
        X_MIN: int,
        X_MAX: int,
        Y_MIN: int,
        Y_MAX: int,
        low: int,
        high: int,
    ) -> None:
        target_y = round(linear_transform(target, low, high, Y_MAX, Y_MIN))
        pygame.draw.line(self.screen, self.RED, (X_MIN, target_y), (X_MAX, target_y))

    def draw_coordinates(
        self,
        queue: WaveQueue,
        X_MIN: int,
        X_MAX: int,
        Y_MIN: int,
        Y_MAX: int,
        low: int,
        high: int,
    ) -> None:
        queue_list = list(queue)
        if not queue_list:
            return
        for i, series in enumerate(zip(*queue_list)):
            points = self.generate_coordinates(
                list(series), X_MIN, X_MAX, Y_MIN, Y_MAX, low, high
            )
            if len(points) < 2:
                continue
            pygame.draw.lines(self.screen, self.colors[i], False, points)

    def draw_waveform(
        self,
        queue: WaveQueue,
        X_MIN: int,
        X_MAX: int,
        Y_MIN: int,
        Y_MAX: int,
        steps: int = 10,
        target_y: Optional[float] = None,
    ) -> None:
        if target_y:
            self.draw_target_line(
                target_y, X_MIN, X_MAX, Y_MIN, Y_MAX, queue.low, queue.high
            )
        self.draw_y_axis(X_MIN, X_MAX, Y_MIN, Y_MAX, queue.low, queue.high, steps)
        self.draw_coordinates(queue, X_MIN, X_MAX, Y_MIN, Y_MAX, queue.low, queue.high)

    # ------------------------------------------------------------------ #
    #  Zone redraws — each returns the rect it touched, or None if it
    #  decided the zone was unchanged since last frame.
    # ------------------------------------------------------------------ #

    def _redraw_header(self, dirty: List[pygame.Rect]) -> None:
        """Hero current temp + setpoint + boil state + water % + countdown."""
        temp_queue = self.wave_queues.get("temp")
        if temp_queue and len(temp_queue) > 0:
            raw_temp = temp_queue[-1][-1]  # last tuple, last entry = raw TSIC reading
        else:
            raw_temp = 0.0
        # Setpoint lives on the queue as its target_y
        setpoint = temp_queue.target_y if temp_queue is not None else 0
        boiling = self.boiler.get_boiling()
        water = round(self.ranger.get_current_distance(), 0)
        countdown = int(
            config.TURN_OFF_SECONDS - (time.perf_counter() - self.get_started_time())
        )

        hero = f"{raw_temp:.1f}°"
        target = f"→{setpoint:.0f}°" if setpoint else "→---"
        boil = "●BOIL" if boiling else "○OFF"
        water_str = f"H2O {water:.0f}%"
        count_str = f"{countdown}s"

        key = f"{hero}|{target}|{boil}|{water_str}|{count_str}"
        if key == self._last_header:
            return
        self._last_header = key

        self.screen.fill(self.BLACK, self.rect_header)

        hero_surf = self._render(hero, 28, self.WHITE)
        self.screen.blit(hero_surf, (4, 0))

        target_color = self.GREY if not boiling else self.WHITE
        self.screen.blit(self._render(target, 12, target_color), (120, 4))

        boil_color = self.RED if boiling else self.GREY
        self.screen.blit(self._render(boil, 12, boil_color), (120, 16))

        water_color = self.WHITE if water > 10 else self.RED
        self.screen.blit(self._render(water_str, 12, water_color), (210, 4))
        self.screen.blit(self._render(count_str, 12, self.WHITE), (210, 16))

        dirty.append(self.rect_header)

    def _redraw_brew_strip(self, dirty: List[pygame.Rect]) -> None:
        """Single 12pt line with brew/preinfuse/flow/scale values."""
        brew_s = round(self.brewing_timer.get_time_since_started(), 1)
        pre_s = round(self.pump.get_time_since_started_preinfuse(), 1)
        flow_ml = round(self.flow.get_millilitres(), 1)
        scale_g = self.bluetooth_scale.get_scale_weight()

        text = f"Brew {brew_s}s  Pre {pre_s}s  Flow {flow_ml}mL  Scale {scale_g}g"
        if text == self._last_brew:
            return
        self._last_brew = text

        self.screen.fill(self.BLACK, self.rect_brew)
        self.screen.blit(self._render(text, 12, self.WHITE), (4, 32))
        dirty.append(self.rect_brew)

    def _redraw_temp_legend(self, dirty: List[pygame.Rect]) -> None:
        """2 columns x 3 rows of color-coded thermal-mass readings.

        The 7th element of the tuple (raw temperature) is the hero
        number in the header, so we render only the first 6 here."""
        queue = self.wave_queues.get("temp")
        if not queue or len(queue) == 0:
            # Still need to clear the zone once
            token: Tuple[Any, ...] = ()
            if token == self._last_legend:
                return
            self._last_legend = token
            self.screen.fill(self.BLACK, self.rect_temp_legend)
            dirty.append(self.rect_temp_legend)
            return

        latest = queue[-1]
        labels = queue.queue_labels[:6]
        values = latest[:6]

        token = (tuple(labels), tuple(round(v, 1) for v in values))
        if token == self._last_legend:
            return
        self._last_legend = token

        self.screen.fill(self.BLACK, self.rect_temp_legend)

        # 2 columns, 3 rows. Column widths chosen so "shell  28.0" fits.
        col_x = (4, 84)
        row_y = (48, 60, 72)
        for i, (label, value) in enumerate(zip(labels, values)):
            row = i // 2
            col = i % 2
            text = f"{label:<5} {value:5.1f}"
            self.screen.blit(
                self._render(text, 12, self.colors[i]),
                (col_x[col], row_y[row]),
            )

        dirty.append(self.rect_temp_legend)

    def _redraw_temp_wave(self, dirty: List[pygame.Rect]) -> None:
        queue = self.wave_queues.get("temp")
        token = self._wave_token(queue)
        if token == self._last_temp_wave_token:
            return
        self._last_temp_wave_token = token

        self.screen.fill(self.BLACK, self.rect_temp_wave)
        if queue is not None:
            self.draw_waveform(
                queue=queue,
                X_MIN=queue.X_MIN,
                X_MAX=queue.X_MAX,
                Y_MIN=queue.Y_MIN,
                Y_MAX=queue.Y_MAX,
                steps=queue.steps,
                target_y=queue.target_y,
            )
        dirty.append(self.rect_temp_wave)

    def _redraw_flow_header(self, dirty: List[pygame.Rect]) -> None:
        flow_rate = self.flow.get_flow_rate() or 0.0
        text = f"Flow {flow_rate:.1f} mL/s"
        if text == self._last_flow_header:
            return
        self._last_flow_header = text

        self.screen.fill(self.BLACK, self.rect_flow_header)
        self.screen.blit(self._render(text, 12, self.WHITE), (164, 48))
        dirty.append(self.rect_flow_header)

    def _redraw_flow_wave(self, dirty: List[pygame.Rect]) -> None:
        queue = self.wave_queues.get("flow")
        token = self._wave_token(queue)
        if token == self._last_flow_wave_token:
            return
        self._last_flow_wave_token = token

        self.screen.fill(self.BLACK, self.rect_flow_wave)
        if queue is not None:
            self.draw_waveform(
                queue=queue,
                X_MIN=queue.X_MIN,
                X_MAX=queue.X_MAX,
                Y_MIN=queue.Y_MIN,
                Y_MAX=queue.Y_MAX,
                steps=queue.steps,
                target_y=queue.target_y,
            )
        dirty.append(self.rect_flow_wave)

    def _redraw_boiler_header(self, dirty: List[pygame.Rect]) -> None:
        pwm_pct = self.boiler.pwm.get_display_value()
        text = f"Pwr {pwm_pct}%"
        if text == self._last_boiler_header:
            return
        self._last_boiler_header = text

        self.screen.fill(self.BLACK, self.rect_boiler_header)
        self.screen.blit(self._render(text, 12, self.WHITE), (164, 145))
        dirty.append(self.rect_boiler_header)

    def _redraw_boiler_wave(self, dirty: List[pygame.Rect]) -> None:
        queue = self.wave_queues.get("boiler")
        token = self._wave_token(queue)
        if token == self._last_boiler_wave_token:
            return
        self._last_boiler_wave_token = token

        self.screen.fill(self.BLACK, self.rect_boiler_wave)
        if queue is not None:
            self.draw_waveform(
                queue=queue,
                X_MIN=queue.X_MIN,
                X_MAX=queue.X_MAX,
                Y_MIN=queue.Y_MIN,
                Y_MAX=queue.Y_MAX,
                steps=queue.steps,
                target_y=queue.target_y,
            )
        dirty.append(self.rect_boiler_wave)

    @staticmethod
    def _wave_token(queue: Optional[WaveQueue]) -> Any:
        """Cheap "has the queue changed?" token. Length plus the id() of
        the most recent tuple (which is a fresh object on every
        add_to_queue call) is enough to detect new data without
        comparing values."""
        if queue is None or len(queue) == 0:
            return (0, None)
        return (len(queue), id(queue[-1]))

    # ------------------------------------------------------------------ #
    #  Frame composition + main loop
    # ------------------------------------------------------------------ #

    def _render_frame(self) -> List[pygame.Rect]:
        """Run one frame's worth of redraws. Returns the list of rects
        that actually changed and need to be flushed to the framebuffer.

        Split out from ``start`` so tests can drive a single frame."""
        dirty: List[pygame.Rect] = []
        self._redraw_header(dirty)
        self._redraw_brew_strip(dirty)
        self._redraw_temp_legend(dirty)
        self._redraw_temp_wave(dirty)
        self._redraw_flow_header(dirty)
        self._redraw_flow_wave(dirty)
        self._redraw_boiler_header(dirty)
        self._redraw_boiler_wave(dirty)
        return dirty

    def stop(self) -> None:
        self._stop_event.set()

    def start(self) -> None:
        logger.info("display loop starting at %s fps", config.DISPLAY_FPS)
        # First frame: clear the whole screen so any garbage from boot
        # is gone before partial updates start touching individual zones.
        self.screen.fill(self.BLACK)
        pygame.display.update()

        clock = pygame.time.Clock()
        frame = 0
        try:
            while not self._stop_event.is_set():
                try:
                    for event in pygame.event.get():
                        x, _ = pygame.mouse.get_pos()
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            if x < 160:
                                self.buttons.rising_button_one()
                            else:
                                self.buttons.rising_button_two()
                        if event.type == pygame.MOUSEBUTTONUP:
                            if x < 160:
                                self.buttons.falling_button_one()
                            else:
                                self.buttons.falling_button_two()

                    dirty = self._render_frame()
                    if dirty:
                        # Partial update — only the rects we touched
                        # get flushed to the framebuffer. When nothing
                        # changed (rare with live data) we skip the
                        # flush entirely.
                        pygame.display.update(dirty)

                    frame += 1
                    if frame == 1 or frame % 240 == 0:
                        logger.info("display heartbeat: frame=%d", frame)

                    clock.tick(config.DISPLAY_FPS)
                except Exception:
                    logger.exception("display loop iteration failed (frame=%d)", frame)
                    time.sleep(1)
        finally:
            logger.info("display loop exiting after %d frames", frame)
            pygame.display.quit()
            pygame.quit()


if __name__ == "__main__":
    from mock import MagicMock

    bluetooth_scale = MagicMock()
    bluetooth_scale.get_scale_weight = lambda: 0
    boiler = MagicMock()
    boiler.pwm.get_display_value = lambda: 0
    buttons = MagicMock()
    pump = MagicMock()
    pump.get_time_since_started_preinfuse = lambda: 0
    brewing_timer = MagicMock()
    brewing_timer.get_time_since_started = lambda: 0
    ranger = MagicMock()
    ranger.get_current_distance = lambda: 0
    flow = MagicMock()
    flow.get_millilitres = lambda: 10.0123
    time_started = time.perf_counter()
    wave_queues = {
        "temp": WaveQueue(
            90,
            100,
            X_MIN=config.TEMP_X_MIN,
            X_MAX=config.TEMP_X_MAX,
            Y_MIN=config.TEMP_Y_MIN,
            Y_MAX=config.TEMP_Y_MAX,
            target_y=config.TARGET_TEMP,
        ),
        "flow": WaveQueue(
            0,
            3,
            X_MIN=config.FLOW_X_MIN,
            X_MAX=config.FLOW_X_MAX,
            Y_MIN=config.FLOW_Y_MIN,
            Y_MAX=config.FLOW_Y_MAX,
            steps=5,
        ),
        "boiler": WaveQueue(
            0,
            100,
            X_MIN=config.BOILER_X_MIN,
            X_MAX=config.BOILER_X_MAX,
            Y_MIN=config.BOILER_Y_MIN,
            Y_MAX=config.BOILER_Y_MAX,
            steps=5,
        ),
    }

    dis = Display(
        bluetooth_scale=bluetooth_scale,
        boiler=boiler,
        buttons=buttons,
        brewing_timer=brewing_timer,
        pump=pump,
        ranger=ranger,
        flow=flow,
        get_started_time=lambda: time_started,
        wave_queues=wave_queues,
    )
    try:
        dis.start()
    except Exception:
        logger.exception("display crashed")
        dis.stop()
