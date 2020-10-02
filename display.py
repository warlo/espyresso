import os
import sys
import threading
import time
from collections import deque
from utils import linear_transform

import pygame
from pygame.locals import *

import config

WIDTH = 320
HEIGHT = 240

AXIS_WIDTH = 28

TEMP_X_MIN = 0 + AXIS_WIDTH
TEMP_X_MAX = 160
TEMP_Y_MIN = 50
TEMP_Y_MAX = 240

FLOW_X_MIN = 160 + AXIS_WIDTH
FLOW_X_MAX = 320
FLOW_Y_MIN = 50
FLOW_Y_MAX = 140

PRESSURE_X_MIN = 160 + AXIS_WIDTH
PRESSURE_X_MAX = 320
PRESSURE_Y_MIN = 150
PRESSURE_Y_MAX = 240

ZOOM = 2


class Queue(deque):
    def __init__(self, low, high, length, *args, **kwargs) -> None:
        self.low = low
        self.high = high
        self.min_low = low
        self.max_high = high

        self.length = length
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


class Display(threading.Thread):
    def __init__(
        self,
        *args,
        boiler=None,
        pump=None,
        ranger=None,
        flow=None,
        target_temp=95,
        get_started_time=None,
        **kwargs,
    ):
        os.environ["SDL_FBDEV"] = "/dev/fb1"
        # Uncomment if you have a touch panel and find the X value for your device
        # os.environ["SDL_MOUSEDRV"] = "TSLIB"
        # os.environ["SDL_MOUSEDEV"] = "/dev/input/eventX"

        pygame.display.init()
        pygame.mouse.set_visible(False)
        pygame.font.init()

        # set up the window
        pygame.event.set_allowed(None)
        flags = pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)

        font = "nk57-monospace-cd-rg.ttf"
        self.big_font = pygame.font.Font(font, 42)
        self.medium_font = pygame.font.Font(font, 28)
        self.small_font = pygame.font.Font(font, 12)

        # set up the colors
        self.BLACK = (0, 0, 0)
        self.GREY = (100, 100, 100)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)

        self.temp_queue = Queue(90, 100, TEMP_X_MAX - TEMP_X_MIN)
        self.flow_queue = Queue(0, 2, FLOW_X_MAX - FLOW_X_MIN)
        self.pressure_queue = Queue(8, 10, PRESSURE_X_MAX - PRESSURE_X_MIN)

        self.target_temp = target_temp
        self.notification = ""

        self.boiler = boiler
        self.pump = pump
        self.ranger = ranger
        self.flow = flow
        self.get_started_time = get_started_time

        self.running = True

        super().__init__(*args, **kwargs)

    def generate_coordinate(self, temp, index, Y_MIN, Y_MAX, low, high):
        return (index, round(linear_transform(temp, low, high, Y_MAX, Y_MIN)))

    def generate_coordinates(self, queue, X_MIN, X_MAX, Y_MIN, Y_MAX, low, high):
        return [
            self.generate_coordinate(
                temp, X_MIN + index * ZOOM, Y_MIN, Y_MAX, low, high
            )
            for index, temp in enumerate(queue)
        ]

    def add_to_temp_queue(self, new_temp):
        self.temp_queue.add_to_queue(new_value=new_temp)

    def add_to_pressure_queue(self, new_value):
        self.pressure_queue.add_to_queue(new_value=new_value)

    def add_to_flow_queue(self, new_value):
        self.flow_queue.add_to_queue(new_value=new_value)

    def draw_notification(self):
        label = self.big_font.render(f"{self.notification}", 1, self.WHITE)
        self.screen.blit(label, ((WIDTH / 2) - 25, (HEIGHT / 2)))

    def draw_waveform(self, queue, X_MIN, X_MAX, Y_MIN, Y_MAX, steps=10, target_y=None):
        if target_y:
            self.draw_target_line(
                target_y, X_MIN, X_MAX, Y_MIN, Y_MAX, queue.low, queue.high
            )
        self.draw_y_axis(X_MIN, X_MAX, Y_MIN, Y_MAX, queue.low, queue.high, steps)
        self.draw_coordinates(queue, X_MIN, X_MAX, Y_MIN, Y_MAX, queue.low, queue.high)

    def draw_y_axis(self, X_MIN, X_MAX, Y_MIN, Y_MAX, low, high, number_of_steps):
        pygame.draw.line(self.screen, self.WHITE, (X_MIN, Y_MAX), (X_MIN, Y_MIN))
        pygame.draw.line(self.screen, self.WHITE, (X_MIN, Y_MAX), (X_MAX, Y_MAX))
        range_steps = int(
            (high * number_of_steps - low * number_of_steps) / number_of_steps
        )

        steps = []
        rounded = True
        for i in range(low * number_of_steps, high * number_of_steps, range_steps):
            closest_step = i / number_of_steps

            y_val = round(linear_transform(closest_step, low, high, Y_MAX, Y_MIN))
            if y_val < Y_MIN:
                continue

            steps.append((closest_step, y_val))

            if not closest_step.is_integer():
                rounded = False

        for (step, y_val) in steps:
            if rounded:
                step = round(step)
            label = self.small_font.render("{}".format(str(step)), 1, self.WHITE)
            self.screen.blit(label, (X_MIN - 24, y_val - 16))  # Number on Y-axis step

            # Transparent line
            horizontal_line = pygame.Surface((X_MAX - X_MIN, 1), flags=pygame.SRCALPHA)
            horizontal_line.fill(
                (255, 255, 255, 100)
            )  # You can change the 100 depending on what transparency it is.
            self.screen.blit(horizontal_line, (X_MIN, y_val))  # Line on Y-axis

    def draw_degrees(self, degrees=0):
        label = self.big_font.render(f"{round(degrees, 1)}\u00B0C", 1, self.WHITE)
        self.screen.blit(label, (max(0, (100 - int(label.get_rect().width))), 0))

    def draw_boiling_label(self, boiling=False, time_left=0):
        time_label = self.small_font.render(f"Time:  {time_left}", 1, self.WHITE)
        power_label = self.small_font.render(
            f"Power: {self.boiler.pwm.get_display_value()}%", 1, self.WHITE
        )
        water_value = round(self.ranger.get_current_distance(), 1)
        water_label = self.small_font.render(
            f"Water: {water_value}%", 1, self.WHITE if water_value > 10 else self.RED
        )
        on_off_label = self.small_font.render("ON" if boiling else "OFF", 1, self.RED)

        self.screen.blit(time_label, (200, 0))
        self.screen.blit(power_label, (200, 14))
        self.screen.blit(water_label, (200, 28))

        pygame.draw.circle(
            self.screen, self.RED if boiling else self.GREY, (300, 12), 10
        )
        self.screen.blit(
            on_off_label, (300 - int(on_off_label.get_rect().width / 2), 24)
        )

    def draw_brewing_timer(self, time_since_started=0):
        label = self.medium_font.render(
            f"{round(time_since_started, 1)}", 1, self.WHITE
        )
        self.screen.blit(label, (140, 0))

    def draw_flow(self, millilitres=0):
        label = self.small_font.render(f"{round(millilitres, 1)}mL", 1, self.WHITE)
        self.screen.blit(label, (140, 30))

    def draw_target_line(self, target, X_MIN, X_MAX, Y_MIN, Y_MAX, low, high):
        target_y = round(linear_transform(target, low, high, Y_MAX, Y_MIN))
        pygame.draw.line(self.screen, self.RED, (X_MIN, target_y), (X_MAX, target_y))

    def draw_coordinates(self, queue, X_MIN, X_MAX, Y_MIN, Y_MAX, low, high):
        points = self.generate_coordinates(queue, X_MIN, X_MAX, Y_MIN, Y_MAX, low, high)
        if not points:
            return

        previous_point = points[0]
        for point in points[1:]:
            pygame.draw.line(self.screen, self.GREEN, previous_point, point)
            previous_point = point

    def stop(self):
        self.running = False
        pygame.quit()

    def run(self):
        while self.running:
            time_left = int(
                config.TURN_OFF_SECONDS - (time.time() - self.get_started_time())
            )
            self.screen.fill(self.BLACK)
            self.draw_degrees(self.temp_queue[-1] if self.temp_queue else 0)
            self.draw_boiling_label(self.boiler.get_boiling(), time_left)
            self.draw_brewing_timer(
                time_since_started=self.pump.get_time_since_started_brew()
            )
            self.draw_flow(millilitres=self.flow.get_millilitres())
            if self.notification:
                self.draw_notification()
            self.draw_waveform(
                queue=self.temp_queue,
                X_MIN=TEMP_X_MIN,
                X_MAX=TEMP_X_MAX,
                Y_MIN=TEMP_Y_MIN,
                Y_MAX=TEMP_Y_MAX,
                target_y=self.target_temp,
            )
            self.draw_waveform(
                queue=self.flow_queue,
                X_MIN=FLOW_X_MIN,
                X_MAX=FLOW_X_MAX,
                Y_MIN=FLOW_Y_MIN,
                Y_MAX=FLOW_Y_MAX,
                steps=5,
            )
            self.draw_waveform(
                queue=self.pressure_queue,
                X_MIN=PRESSURE_X_MIN,
                X_MAX=PRESSURE_X_MAX,
                Y_MIN=PRESSURE_Y_MIN,
                Y_MAX=PRESSURE_Y_MAX,
                steps=5,
            )
            pygame.display.update()
            time.sleep(0.2)

    def test_display(self):
        # run the game loop
        import random
        import time

        v = 25
        try:
            while self.running and v < 1000:
                for event in pygame.event.get():
                    if event.type == QUIT:
                        pygame.quit()
                        sys.exit()
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        print("Pos: %sx%s\n" % pygame.mouse.get_pos())
                v += 1
                self.add_to_temp_queue(random.randint(94, 96))
                self.add_to_flow_queue(random.randint(1, 2))
                self.add_to_pressure_queue(random.randint(8, 10))
                time.sleep(0.1)
        except Exception as e:
            print(e)
            self.stop()


if __name__ == "__main__":
    from mock import Mock

    boiler = Mock()
    boiler.pwm.get_display_value = lambda: 0
    pump = Mock()
    pump.get_time_since_started_brew = lambda: 0
    ranger = Mock()
    ranger.get_current_distance = lambda: 0
    flow = Mock()
    flow.get_millilitres = lambda: 10.0123
    time_started = time.time()
    dis = Display(
        boiler=boiler,
        pump=pump,
        ranger=ranger,
        flow=flow,
        get_started_time=lambda: time_started,
    )
    try:
        dis.start()
        dis.test_display()
    except Exception:
        print("EXCEPTIOON")
        dis.stop()
