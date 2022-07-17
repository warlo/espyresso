# mypy: ignore-errors
import time

import pygame


def waveform():
    pass


def wave(screen):
    samples = [0, 10, 20, 30, 40, 50, 60]

    def scale_samples_to_surf(width, height, samples):
        """Returns a generator containing (x, y) to draw a waveform.

        :param width: width of surface to scale points to.
        :param height: height of surface to scale points to.
        :param samples: an array of signed 1 byte or signed 2 byte.
        """
        # precalculate a bunch of variables, so not done in the loop.
        len_samples = len(samples)
        width_per_sample = width / len_samples
        height_1 = height - 1

        return (
            (
                int((sample_number + 1) * width_per_sample),
                int(
                    (1.0 - (factor * (samples[sample_number] + normalize_modifier)))
                    * (height_1)
                ),
            )
            for sample_number in range(len_samples)
        )

    def draw_wave(
        surf, samples, wave_color=(0, 0, 0), background_color=pygame.Color("white")
    ):
        """Draw array of sound samples as waveform into the 'surf'.

        :param surf: Surface we want to draw the wave form onto.
        :param samples: an array of signed 1 byte or signed 2 byte.
        :param wave_color: color to draw the wave form.
        :param background_color: to fill the 'surf' with.
        """
        if background_color is not None:
            surf.fill(background_color)
        width, height = surf.get_size()
        points = tuple([(x, y) for x, y in enumerate(samples)])
        pygame.draw.lines(surf, wave_color, False, points)

    # Here we should how to draw it onto a screen.
    waveform = pygame.Surface((320, 200)).convert_alpha()
    draw_wave(waveform, samples)
    # screen.fill((255, 255, 255))
    screen.blit(waveform, (160, 100))


pygame.init()
size = (800, 600)
screen = pygame.display.set_mode(size)

background = pygame.Surface(screen.get_size())
background = background.convert()
background.fill((220, 220, 220))

screen.blit(background, (0, 0))
pygame.display.update()

pygame.draw.line(screen, (0, 0, 0), (300, 50), (300, 550))
pygame.draw.line(screen, (0, 0, 0), (500, 50), (500, 550))
pygame.draw.line(screen, (0, 0, 0), (100, 200), (700, 200))
pygame.draw.line(screen, (0, 0, 0), (100, 400), (700, 400))
while 1:  # main game loop
    print("1")
    time.sleep(1)
    pygame.display.update()
    # waveform = wave(screen)
    # pygame.display.update(waveform)
