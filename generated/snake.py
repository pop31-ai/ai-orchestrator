import pygame
import random

W, H = 600, 600
CELL = 20
COLS, ROWS = W // CELL, H // CELL
FPS = 10

pygame.init()
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 24)

snake = [(COLS // 2, ROWS // 2)]
dx, dy = 1, 0
food = (random.randint(0, COLS - 1), random.randint(0, ROWS - 1))
score = 0
running = True

while running:
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_UP and dy == 0:
                dx, dy = 0, -1
            if e.key == pygame.K_DOWN and dy == 0:
                dx, dy = 0, 1
            if e.key == pygame.K_LEFT and dx == 0:
                dx, dy = -1, 0
            if e.key == pygame.K_RIGHT and dx == 0:
                dx, dy = 1, 0

    head = (snake[0][0] + dx, snake[0][1] + dy)

    if head == food:
        snake.insert(0, head)
        score += 10
        food = (random.randint(0, COLS - 1), random.randint(0, ROWS - 1))
        while food in snake:
            food = (random.randint(0, COLS - 1), random.randint(0, ROWS - 1))
    else:
        snake.insert(0, head)
        snake.pop()

    if (head[0] < 0 or head[0] >= COLS or head[1] < 0 or head[1] >= ROWS or
            head in snake[1:]):
        break

    screen.fill((0, 0, 0))
    for seg in snake:
        pygame.draw.rect(screen, (0, 200, 0), (seg[0] * CELL, seg[1] * CELL, CELL - 1, CELL - 1))
    pygame.draw.rect(screen, (200, 0, 0), (food[0] * CELL, food[1] * CELL, CELL, CELL))
    sc = font.render(f"Score: {score}", True, (255, 255, 255))
    screen.blit(sc, (10, 10))
    pygame.display.flip()
    clock.tick(FPS)

screen.blit(font.render("GAME OVER", True, (255, 0, 0)), (W // 2 - 60, H // 2))
pygame.display.flip()
pygame.time.wait(2000)
pygame.quit()
