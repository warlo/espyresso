import pygame, sys, os, math
from collections import deque
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


def get_low_and_high(points):
    pass


class Display:
    def __init__(self, target_temp=95):
        os.environ["SDL_FBDEV"] = "/dev/fb1"
        # Uncomment if you have a touch panel and find the X value for your device
        # os.environ["SDL_MOUSEDRV"] = "TSLIB"
        # os.environ["SDL_MOUSEDEV"] = "/dev/input/eventX"

        # set up the colors
        self.BLACK = (0, 0, 0)
        self.WHITE = (255, 255, 255)
        self.GRAY = (100, 100, 100)
        self.RED = (255, 0, 0)
        self.GREEN = (0, 255, 0)
        self.BLUE = (0, 0, 255)

        pygame.display.init()
        pygame.mouse.set_visible(False)
        pygame.font.init()
        pygame.event.set_allowed(None)
        self.big_font = pygame.font.Font("monospace.ttf", 50)
        self.small_font = pygame.font.Font("monospace.ttf", 16)

        # set up the window
        flags = FULLSCREEN | DOUBLEBUF
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
        self.screen.fill(self.BLACK)
        self.draw_y_axis()

        self.queue = deque()
        self.y_points = deque()
        self.low = 80
        self.high = 100
        self.target_temp = target_temp
        self.notification = ''

    def generate_coordinates(self, temperatures):

        points = [
            (32 + index * 2, linear_transform(temp, self.low, self.high, HEIGHT, 50))
            for index, temp in enumerate(temperatures)
        ]
        return points

    def add_to_queue(self, new_temp):

        popped = None
        if len(self.queue) >= (WIDTH / 2) - 16:
            popped = self.queue.popleft()
            self.y_points.popleft()

        self.queue.append(new_temp)
        self.y_points.append(linear_transform(new_temp, self.low, self.high, HEIGHT, 50))

        if new_temp > self.high:
            self.high = int(new_temp)
        elif new_temp < self.low:
            self.low = int(new_temp)

        if not popped:
            return
        elif popped <= self.low:
            self.low = int(min(self.queue))
        elif popped >= self.high:
            self.high = int(max(self.queue))

    def draw(self, degrees=0):
        self.add_to_queue(degrees)
        self.draw_degrees(degrees)
        if self.notification:
            self.draw_notification()
        self.draw_y_axis()
        self.draw_waveform()
        pygame.display.update()

    def draw_notification(self):
        label = self.big_font.render("{}".format(self.notification), 1, self.WHITE)
        self.screen.blit(label, (WIDTH - 50, 0))

    def draw_y_axis(self):
        pygame.draw.line(self.screen, self.WHITE, (32, 240), (32, 50))
        steps = 10
        for i in range(self.low, self.high, steps):
            closest_ten = int(math.ceil(i / steps)) * steps

            label = self.small_font.render("{}".format(str(closest_ten)), 1, self.WHITE)
            y_val = linear_transform(closest_ten, self.low, self.high, HEIGHT, 50)
            self.screen.blit(label, (4, y_val - (16 / 2)))

            pygame.draw.line(self.screen, self.GRAY, (32, 240), (32, 50))
            """
            # Transparent line
            horizontal_line = pygame.Surface((320, 1), pygame.SRCALPHA)
            horizontal_line.fill(
                (255, 255, 255, 100)
            )  # You can change the 100 depending on what transparency it is.
            self.screen.blit(horizontal_line, (32, y_val))
            """

    def draw_degrees(self, degrees=0):
        #self.screen.fill(self.BLACK, pygame.Rect(0, 0, 320, 50))
        self.screen.fill(self.BLACK)
        label = self.big_font.render("{:.1f}\u00B0C".format(degrees), 1, self.WHITE)
        self.screen.blit(label, (0, 0))

    def draw_waveform(self):
        target_y = linear_transform(self.target_temp, self.low, self.high, HEIGHT, 50)
        pygame.draw.line(self.screen, self.RED, (32, target_y), (320, target_y))

        #y_points = self.generate_coordinates(list(self.queue))
        y_points = self.y_points
        previous_y = y_points[0]
        for i, y_point in enumerate(y_points[1:]):
            pygame.draw.line(self.screen, self.GREEN, (32 + i * 2, previous_y), (32 + (i + 1) * 2, y_point))
            previous_y = y_point

    def stop(self):
        pygame.quit()

    def main(self):
        # run the game loop
        import random, time

        v = 25
        while True:
            for event in pygame.event.get():
                if event.type == QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.MOUSEBUTTONDOWN:
                    print("Pos: %sx%s\n" % pygame.mouse.get_pos())
            v += 1
            self.draw(random.randint(70, 120))
            time.sleep(0.1)
            pygame.display.update()


if __name__ == "__main__":
    dis = Display()
    dis.main()
