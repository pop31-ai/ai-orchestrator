import pygame
import random

W, H = 800, 600
PADDLE_W, PADDLE_H = 120, 15
BALL_SIZE = 12
BRICK_W, BRICK_H = 70, 25
BRICK_ROWS, BRICK_COLS = 6, 10
FPS = 60

pygame.init()
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 36)

paddle = pygame.Rect(W // 2 - PADDLE_W // 2, H - 40, PADDLE_W, PADDLE_H)
ball = pygame.Rect(W // 2, H // 2, BALL_SIZE, BALL_SIZE)
ball_dx, ball_dy = 4, -4
bricks = [pygame.Rect(c * (BRICK_W + 4) + 20, r * (BRICK_H + 4) + 40, BRICK_W, BRICK_H)
          for r in range(BRICK_ROWS) for c in range(BRICK_COLS)]
colors = [(random.randint(50,255), random.randint(50,255), random.randint(50,255)) for _ in bricks]
score = 0
running = True

while running:
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT] and paddle.left > 0:
        paddle.move_ip(-7, 0)
    if keys[pygame.K_RIGHT] and paddle.right < W:
        paddle.move_ip(7, 0)
    ball.move_ip(ball_dx, ball_dy)
    if ball.left <= 0 or ball.right >= W:
        ball_dx = -ball_dx
    if ball.top <= 0:
        ball_dy = -ball_dy
    if ball.bottom >= H:
        running = False
        break
    if ball.colliderect(paddle):
        ball_dy = -ball_dy
    hit = ball.collidelist(bricks)
    if hit != -1:
        bricks.pop(hit)
        colors.pop(hit)
        ball_dy = -ball_dy
        score += 10
    screen.fill((0, 0, 0))
    pygame.draw.rect(screen, (200, 200, 200), paddle)
    pygame.draw.ellipse(screen, (255, 255, 255), ball)
    for brick, color in zip(bricks, colors):
        pygame.draw.rect(screen, color, brick)
    score_text = font.render(f"Score: {score}", True, (255, 255, 255))
    screen.blit(score_text, (10, 10))
    pygame.display.flip()
    clock.tick(FPS)

game_over = font.render("GAME OVER", True, (255, 0, 0))
screen.blit(game_over, (W // 2 - 100, H // 2 - 20))
pygame.display.flip()
pygame.time.wait(2000)
pygame.quit()
