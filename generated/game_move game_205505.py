import pygame, sys, random
pygame.init()
W, H = 400, 400
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 30)
px, py = W // 2, H // 2
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]: px -= 5
    if keys[pygame.K_RIGHT]: px += 5
    if keys[pygame.K_UP]: py -= 5
    if keys[pygame.K_DOWN]: py += 5
    screen.fill((0, 0, 0))
    pygame.draw.circle(screen, (0, 200, 255), (px, py), 20)
    pygame.draw.rect(screen, (255, 255, 0), (random.randint(0, W-10), random.randint(0, H-10), 10, 10))
    screen.blit(font.render("Move with arrows", True, (255, 255, 255)), (100, 350))
    pygame.display.flip(); clock.tick(60)
pygame.quit()
sys.exit()
