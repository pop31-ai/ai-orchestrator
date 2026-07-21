import pygame, sys, random
pygame.init()
W, H = 400, 400
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
snake = [(100, 100)]
dx, dy = 20, 0
food = (random.randrange(0, W, 20), random.randrange(0, H, 20))
score = 0
font = pygame.font.SysFont("Arial", 20)
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP and dy == 0: dx, dy = 0, -20
            if event.key == pygame.K_DOWN and dy == 0: dx, dy = 0, 20
            if event.key == pygame.K_LEFT and dx == 0: dx, dy = -20, 0
            if event.key == pygame.K_RIGHT and dx == 0: dx, dy = 20, 0
    head = (snake[0][0] + dx, snake[0][1] + dy)
    if head[0] < 0 or head[0] >= W or head[1] < 0 or head[1] >= H: running = False
    if head in snake[1:]: running = False
    snake.insert(0, head)
    if head == food:
        score += 1
        food = (random.randrange(0, W, 20), random.randrange(0, H, 20))
    else:
        snake.pop()
    screen.fill((0, 0, 0))
    for s in snake: pygame.draw.rect(screen, (0, 255, 0), (*s, 20, 20))
    pygame.draw.rect(screen, (255, 0, 0), (*food, 20, 20))
    screen.blit(font.render(f"Score: {score}", True, (255, 255, 255)), (10, 10))
    pygame.display.flip()
    clock.tick(10)
pygame.quit()
sys.exit()
