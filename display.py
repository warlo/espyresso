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

    y = (x-a) / (b-a) * (d - c) + c
    return y

def get_low_and_high(points):
    pass

class Display():
    def __init__(self, target_temp=95):
        os.environ["SDL_FBDEV"] = "/dev/fb1"
        # Uncomment if you have a touch panel and find the X value for your device
        #os.environ["SDL_MOUSEDRV"] = "TSLIB"
        #os.environ["SDL_MOUSEDEV"] = "/dev/input/eventX"

        pygame.display.init()
        pygame.mouse.set_visible(False)
        pygame.font.init()

        # set up the window
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))

        # set up the colors
        self.BLACK = (  0,   0,   0)
        self.WHITE = (255, 255, 255)
        self.RED   = (255,   0,   0)
        self.GREEN = (  0, 255,   0)
        self.BLUE  = (  0,   0, 255)

        self.queue = deque()
        self.low = 120
        self.high = 120
        self.target_temp = target_temp

    def generate_coordinates(self, temperatures):

        points = [(32 + index*2, linear_transform(temp, self.low, self.high, HEIGHT, 50)) for index, temp in enumerate(temperatures)]
        return points

    def add_to_queue(self, new_temp):

        popped = None
        if len(self.queue) >= (WIDTH / 2) - 16:
            popped = self.queue.popleft()

        self.queue.append(new_temp)

        if new_temp > self.high:
            self.high = new_temp
        elif new_temp < self.low:
            self.low = new_temp

        if not popped:
            return
        elif popped <= self.low:
            self.low = min(self.queue)
        elif popped >= self.high:
            self.high = max(self.queue)

    def draw(self, degrees = 0):
        self.add_to_queue(degrees)
        self.draw_degrees(degrees)
        self.draw_y_axis()
        self.draw_waveform()
        pygame.display.update()

    def draw_y_axis(self):
        font_size = 16
        font = pygame.font.Font(os.path.join(os.path.dirname(__file__), 'monospace.ttf'), font_size)
        pygame.draw.line(self.screen, self.WHITE, (32, 240), (32, 50))
        steps = 10
        for i in range(self.low, self.high, steps):
            closest_ten = int(math.ceil(i / steps)) * steps

            label = font.render(u"{}".format(str(closest_ten)), 1, self.WHITE)
            y_val = linear_transform(closest_ten, self.low, self.high, HEIGHT, 50)
            self.screen.blit(label, (0, y_val - (font_size / 2)))

            # Transparent line
            horizontal_line = pygame.Surface((320, 1), pygame.SRCALPHA)
            horizontal_line.fill((255, 255, 255, 100)) # You can change the 100 depending on what transparency it is.
            self.screen.blit(horizontal_line, (32, y_val))


    def draw_degrees(self, degrees = 0):
        self.screen.fill(self.BLACK)
        font = pygame.font.Font('monospace.ttf', 50)
        label = font.render(u"{:.1f}\u00B0C".format(degrees), 1, self.WHITE)
        self.screen.blit(label, (0, 0))

    def draw_waveform(self):
        points = self.generate_coordinates(list(self.queue))
        target_y = linear_transform(self.target_temp, self.low, self.high, HEIGHT, 50)
        pygame.draw.line(self.screen, self.RED, (32, target_y), (320, target_y))

        previous_point = points[0]
        for point in points[1:]:
            pygame.draw.line(self.screen, self.GREEN, previous_point, point)
            previous_point = point

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

if __name__ == '__main__':
    dis = Display()
    dis.main()
