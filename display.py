import os
import sys
import threading
import time
from collections import deque

import config
import pygame
from pygame.locals import *

WIDTH = 320
HEIGHT = 240


def linear_transform(x, a, b, c, d):
    """
    Map X within [A, B] to [C, D]
    linear_transform(70, 70, 120, 240, 50) => 240
    linear_transform(120, 70, 120, 240, 50) => 50
    """

    y = (x - a) / (b - a) * (d - c) + c
    return y


class Display(threading.Thread):
    def __init__(self, started_time, *args, boiler=None, target_temp=95, **kwargs):
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

        self.big_font = pygame.font.Font("monospace.ttf", 48)
        self.small_font = pygame.font.Font("monospace.ttf", 16)

        # set up the colors
        self.BLACK = (0, 0, 0)
        self.GREY = (100, 100, 100)
        self.WHITE = (255, 255, 255)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)

        self.queue = deque()
        self.low = 90
        self.high = 100
        self.target_temp = target_temp
        self.notification = ""

        self.boiler = boiler
        self.started_time = started_time

        self.running = True

        super().__init__(*args, **kwargs)

    def generate_coordinate(self, temp, index):
        return (
            32 + index * 2,
            round(linear_transform(temp, self.low, self.high, HEIGHT, 50)),
        )

    def generate_coordinates(self, temperatures):

        return [
            self.generate_coordinate(temp, index)
            for index, temp in enumerate(temperatures)
        ]

    def add_to_queue(self, new_temp):

        popped = None
        if len(self.queue) >= (WIDTH / 2) - 16:
            popped = self.queue.popleft()

        self.queue.append(new_temp)

        if new_temp > self.high:
            self.high = int(new_temp)
        elif new_temp < self.low:
            self.low = int(new_temp)

        if not popped:
            return
        elif int(popped) >= self.low:
            self.low = int(min(min(self.queue), 90))
        elif int(popped) >= self.high:
            self.high = int(max(max(self.queue), 100))

    def draw_notification(self):
        label = self.big_font.render("{}".format(self.notification), 1, self.WHITE)
        self.screen.blit(label, ((WIDTH / 2) - 25, (HEIGHT / 2)))

    def draw_y_axis(self):
        pygame.draw.line(self.screen, self.WHITE, (32, 240), (32, 50))
        steps = int((self.high - self.low) / 10)
        for i in range(self.low, self.high, steps):
            closest_ten = int(round(i / steps)) * steps

            label = self.small_font.render("{}".format(str(closest_ten)), 1, self.WHITE)
            y_val = round(
                linear_transform(closest_ten, self.low, self.high, HEIGHT, 50)
            )
            if y_val < 50:
                continue
            self.screen.blit(label, (4, y_val - 8))  # Number on Y-axis step

            # Transparent line
            horizontal_line = pygame.Surface((320, 1), flags=pygame.SRCALPHA)
            horizontal_line.fill(
                (255, 255, 255, 100)
            )  # You can change the 100 depending on what transparency it is.
            self.screen.blit(horizontal_line, (32, y_val))  # Line on Y-axis

    def draw_degrees(self, degrees=0):
        self.screen.fill(self.BLACK)
        label = self.big_font.render("{:.1f}\u00B0C".format(degrees), 1, self.WHITE)
        self.screen.blit(label, (0, 0))

    def draw_boiling_label(self, boiling=False, time_left=0):
        if boiling:
            label = self.small_font.render("ON", 1, self.RED)
        else:
            label = self.small_font.render("OFF", 1, self.RED)
        time_label = self.small_font.render(str(time_left), 1, self.WHITE)
        self.screen.blit(time_label, (240 - int(time_label.get_rect().width / 2), 24))
        self.screen.blit(label, (300 - int(label.get_rect().width / 2), 24))
        pygame.draw.circle(
            self.screen, self.RED if boiling else self.GREY, (300, 12), 10
        )

    def draw_waveform(self):
        target_y = round(
            linear_transform(self.target_temp, self.low, self.high, HEIGHT, 50)
        )
        pygame.draw.line(self.screen, self.RED, (32, target_y), (320, target_y))

        points = self.generate_coordinates(list(self.queue))
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
            time_left = int(config.TURN_OFF_SECONDS - (time.time() - self.started_time))
            self.draw_degrees(self.queue[-1] if self.queue else 0)
            self.draw_boiling_label(self.boiler.boiling, time_left)
            if self.notification:
                self.draw_notification()
            self.draw_y_axis()
            self.draw_waveform()
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
                self.add_to_queue(random.randint(70, 120))
                time.sleep(0.1)
        except Exception:
            self.stop()


if __name__ == "__main__":
    from boiler import Boiler

    boiler = Boiler(boiling=False)
    dis = Display(boiler=boiler, started_time=time.time())
    dis.start()
    dis.test_display()
