import pygame, sys, os
from collections import deque
from pygame.locals import *

WIDTH = 320
HEIGHT = 240

def generate_coordinate():

    point = (x, HEIGHT - (y * 1.33))
    return point

class Display():
    def __init__(self):
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
        self.queue.append(0)

    def draw(self, degrees = 0):
        self.queue.popleft()
        self.queue.append(degrees)

        self.draw_degrees(degrees)
        self.draw_waveform()

    def draw_degrees(self, degrees = 0):
        self.screen.fill(self.BLACK)
        myfont = pygame.font.Font('monospace.ttf', 50)
        label = myfont.render(u"{:.1f}\u00B0C".format(degrees), 1, self.WHITE)
        self.screen.blit(label, (0, 0))
        pygame.display.update()

    def draw_waveform(self):
        print(self.queue)
        pass


    def stop(self):
        pygame.quit()

    def main(self):
        # run the game loop
        while True:
            for event in pygame.event.get():
                if event.type == QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.MOUSEBUTTONDOWN:
                    print("Pos: %sx%s\n" % pygame.mouse.get_pos())
            self.draw_degrees()
            pygame.display.update()

if __name__ == '__main__':
    dis = Display()
    dis.main()
