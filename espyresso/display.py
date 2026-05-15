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

        # set up the window
        pygame.event.set_allowed(None)
        if not config.DEBUG:
            flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
        else:
            flags = pygame.HWSURFACE | pygame.DOUBLEBUF
        self.screen = pygame.display.set_mode((config.WIDTH, config.HEIGHT), flags)

        font = str(Path(__file__).parent / "nk57-monospace-cd-rg.ttf")
        self.big_font = pygame.font.Font(font, 42)
        self.medium_font = pygame.font.Font(font, 28)
        self.small_font = pygame.font.Font(font, 12)

        # Render cache: pygame.font.Font.render() allocates a new SDL surface
        # per call. Doing that ~45×/frame at 10 Hz on a Pi Zero caused heap
        # fragmentation and eventual OOM. We cache by (text, font_size, color)
        # with LRU eviction, so static labels and most dynamic values become
        # zero-allocation blits after the first render.
        self._fonts: Dict[int, pygame.font.Font] = {
            42: self.big_font,
            28: self.medium_font,
            12: self.small_font,
        }
        self._render_cache: "OrderedDict[Tuple[str, int, Tuple[int, int, int]], pygame.Surface]" = OrderedDict()

        # Pre-rendered translucent horizontal grid line, keyed by width.
        # Previously this was a fresh SRCALPHA surface per y-axis step per
        # queue per frame — the dominant leak source.
        self._hline_cache: Dict[int, pygame.Surface] = {}

        # set up the colors
        self.BLACK = (0, 0, 0)
        self.GREY = (100, 100, 100)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.LIGHT_BLUE = (0, 255, 255)
        self.BLUE = (0, 0, 255)
        self.ORANGE = (255, 140, 0)
        self.YELLOW = (255, 255, 0)
        self.PINK = (255, 0, 255)
        self.colors = [
            self.GREEN,
            self.ORANGE,
            self.LIGHT_BLUE,
            self.BLUE,
            self.WHITE,
            self.PINK,
            self.YELLOW,
        ]

        self.notification: str = ""
        self.notification_updated = time.perf_counter()
        self.notification_timer: Optional[float] = None

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

    def _render(
        self,
        text: str,
        size: int,
        color: Tuple[int, int, int],
    ) -> pygame.Surface:
        """Return a cached rendered Surface for (text, font size, color).

        The returned Surface is reused across frames; callers must not mutate
        it (blitting is fine — that's read-only)."""
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
        """Return a cached translucent 1-px horizontal line of the given width."""
        surf = self._hline_cache.get(width)
        if surf is None:
            surf = pygame.Surface((width, 1), flags=pygame.SRCALPHA)
            surf.fill((255, 255, 255, 100))
            self._hline_cache[width] = surf
        return surf

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
        values: List[float],
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

    def draw_notification(self) -> None:
        notification = self.buttons.get_notification()

        if not notification:
            return None

        label = self._render(f"{notification}", 42, self.WHITE)
        self.screen.blit(label, ((config.WIDTH / 2) - 25, (config.HEIGHT / 2)))

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

        range_steps = int(
            (high * number_of_steps - low * number_of_steps) / number_of_steps
        )

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
            self.screen.blit(label, (X_MIN - 24, y_val - 8))  # Number on Y-axis step
            self.screen.blit(hline, (X_MIN, y_val))  # Line on Y-axis

    def draw_degrees(self, queue: Optional[WaveQueue]) -> None:
        if not queue:
            return
        degrees = queue[-1]
        # Sort *indices* by descending value. Sorting by value and then
        # looking up via list.index() collapses duplicates onto the first
        # match (e.g. all thermal masses at room temperature on a cold
        # boot), hiding every series after the first.
        order = sorted(range(len(degrees)), key=lambda k: -degrees[k])

        for row, idx in enumerate(order):
            label = self._render(
                f"{queue.queue_labels[idx]}: {round(degrees[idx], 1)}\u00B0C",
                12,
                self.colors[idx],
            )
            self.screen.blit(
                label, (max(0, (100 - int(label.get_rect().width))), 12 * row)
            )

    def draw_boiling_label(self, boiling: bool = False, time_left: float = 0) -> None:
        time_label = self._render(f"Time:  {time_left}", 12, self.WHITE)
        power_label = self._render(
            f"Power: {self.boiler.pwm.get_display_value()}%", 12, self.WHITE
        )
        water_value = round(self.ranger.get_current_distance(), 1)
        water_label = self._render(
            f"Water: {water_value}%", 12, self.WHITE if water_value > 10 else self.RED
        )
        on_off_label = self._render("ON" if boiling else "OFF", 12, self.RED)

        self.screen.blit(time_label, (200, 0))
        self.screen.blit(power_label, (200, 14))
        self.screen.blit(water_label, (200, 28))

        pygame.draw.circle(
            self.screen, self.RED if boiling else self.GREY, (300, 12), 10
        )
        self.screen.blit(
            on_off_label, (300 - int(on_off_label.get_rect().width / 2), 24)
        )

    def draw_brewing_timer(self, time_since_started: float = 0) -> None:
        label = self._render(f"{round(time_since_started, 1)}", 12, self.WHITE)
        self.screen.blit(label, (140, 0))

    def draw_preinfuse_timer(self, time_since_started: float = 0) -> None:
        label = self._render(f"{round(time_since_started, 1)}", 12, self.WHITE)
        self.screen.blit(label, (140, 14))

    def draw_flow(self, millilitres: float = 0) -> None:
        label = self._render(f"{round(millilitres, 1)}mL", 12, self.WHITE)
        self.screen.blit(label, (140, 28))

    def draw_scale_weight(self, scale_weight: float = 0) -> None:
        label = self._render(f"{scale_weight}g", 12, self.WHITE)
        self.screen.blit(label, (140, 42))

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
        for i in range(len(queue_list[0]) if len(queue_list) > 0 else 0):
            points = self.generate_coordinates(
                [tup[i] for tup in queue_list], X_MIN, X_MAX, Y_MIN, Y_MAX, low, high
            )
            if not points:
                return

            color = self.colors[i]
            previous_point = points[0]
            for point in points[1:]:
                pygame.draw.line(self.screen, color, previous_point, point)
                previous_point = point

    def stop(self) -> None:
        self._stop_event.set()

    def start(self) -> None:
        # Clock.tick caps the frame rate but, unlike a fixed time.sleep, it
        # subtracts the time spent rendering. Total cycle length stays
        # bounded so the display thread predictably yields the GIL to the
        # pigpio temperature callback.
        logger.info("display loop starting at %s fps", config.DISPLAY_FPS)
        clock = pygame.time.Clock()
        frame = 0
        try:
            while not self._stop_event.is_set():
                # Per-iteration try/except: a draw failure must not silently
                # kill the loop and freeze the screen.
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

                    time_left = int(
                        config.TURN_OFF_SECONDS
                        - (time.perf_counter() - self.get_started_time())
                    )
                    self.screen.fill(self.BLACK)
                    self.draw_degrees(self.wave_queues.get("temp", None))
                    self.draw_boiling_label(self.boiler.get_boiling(), time_left)
                    self.draw_preinfuse_timer(
                        time_since_started=self.pump.get_time_since_started_preinfuse()
                    )
                    self.draw_brewing_timer(
                        time_since_started=self.brewing_timer.get_time_since_started()
                    )
                    self.draw_flow(millilitres=self.flow.get_millilitres())
                    self.draw_scale_weight(
                        scale_weight=self.bluetooth_scale.get_scale_weight()
                    )
                    self.draw_notification()
                    for queue in self.wave_queues.values():
                        self.draw_waveform(
                            queue=queue,
                            X_MIN=queue.X_MIN,
                            X_MAX=queue.X_MAX,
                            Y_MIN=queue.Y_MIN,
                            Y_MAX=queue.Y_MAX,
                            steps=queue.steps,
                            target_y=queue.target_y,
                        )
                    pygame.display.update()

                    frame += 1
                    # First frame, then once a minute at 4 fps
                    if frame == 1 or frame % 240 == 0:
                        logger.info("display heartbeat: frame=%d", frame)

                    clock.tick(config.DISPLAY_FPS)
                except Exception:
                    logger.exception("display loop iteration failed (frame=%d)", frame)
                    # Avoid spin-logging if the failure persists
                    time.sleep(1)
        finally:
            logger.info("display loop exiting after %d frames", frame)
            pygame.display.quit()
            pygame.quit()

    def test_display(self) -> None:
        # run the game loop
        # import random
        import time

        v = 25
        try:
            while not self._stop_event.is_set() and v < 1000:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit()
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        print("Pos: %sx%s\n" % pygame.mouse.get_pos())
                v += 1
                # self.wave_queues["temp"].add_to_queue(random.randint(94, 96))
                # self.wave_queues["flow"].add_to_queue(random.randint(1, 2))
                # self.wave_queues["boiler"].add_to_queue(random.randint(20, 80))
                time.sleep(0.1)
        except Exception:
            logger.exception("EXC")
            self.stop()


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
            target_y=True,
        ),
        "flow": WaveQueue(
            0,
            100,
            X_MIN=config.FLOW_X_MIN,
            X_MAX=config.FLOW_X_MAX,
            Y_MIN=config.FLOW_Y_MIN,
            Y_MAX=config.FLOW_Y_MAX,
            steps=5,
        ),
        "boiler": WaveQueue(
            0,
            2,
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
        dis.test_display()
    except Exception:
        print("EXCEPTIOON")
        dis.stop()
