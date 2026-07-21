"""
Polynomial Art Generator — Golden Ratio Edition
phi = (1 + sqrt(5)) / 2 ≈ 1.6180339887

Each pixel color = polynomial(phi, x, y) mapped to hue
"""
import pygame
import math

W, H = 800, 800
phi = (1 + math.sqrt(5)) / 2  # golden ratio

pygame.init()
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()

def poly(x, y, coeffs):
    """Evaluate polynomial at (x,y) with golden-ratio-based coefficients."""
    result = 0
    for i, a in enumerate(coeffs):
        # alternate x/y powers, modulated by phi
        if i % 2 == 0:
            result += a * (x ** (i + 1))
        else:
            result += a * (y ** (i + 1))
    return result

# Each formula uses phi differently — experiment!
formulas = [
    # (name, coeffs list)
    ("phi^2 spiral",          [phi**2, -phi, 1, -1/phi]),
    ("phi^n alternating",     [1, -phi, phi**2, -phi**3, phi**4]),
    ("inverse phi waves",     [1/phi, -1, phi, -phi**2, 1/phi**2]),
    ("continued fraction",    [1, 1/phi, 1/phi**2, 1/phi**3]),
    ("phi + cos product",     [phi, -phi**0.5, phi**1.5, -phi**0.3]),
]

def render(formula_idx):
    screen.fill((0, 0, 0))
    pixels = pygame.PixelArray(screen)
    coeffs = formulas[formula_idx][1]
    for x in range(W):
        # normalize to [-1, 1]
        nx = (x / W) * 2 - 1
        for y in range(H):
            ny = (y / H) * 2 - 1
            val = poly(nx, ny, coeffs)
            # map to hue 0-360
            hue = (val * 180 + 360) % 360
            sat = 200
            light = 128 + 64 * math.sin(val * phi)
            # HSL to RGB approximate
            r, g, b = hsl_to_rgb(hue / 360, sat / 255, light / 255)
            pixels[x, y] = (int(r * 255), int(g * 255), int(b * 255))
    pixels.close()

def hsl_to_rgb(h, s, l):
    if s == 0:
        return l, l, l
    def hue2rgb(p, q, t):
        t %= 1
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return hue2rgb(p, q, h + 1/3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1/3)

idx = 0
running = True
render(idx)

while running:
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            running = False
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_RIGHT:
                idx = (idx + 1) % len(formulas)
                render(idx)
            if e.key == pygame.K_LEFT:
                idx = (idx - 1) % len(formulas)
                render(idx)
            if e.key == pygame.K_s:
                pygame.image.save(screen, f"polyart_{idx}.png")
                print(f"Saved polyart_{idx}.png")
    pygame.display.set_caption(f"{formulas[idx][0]} | ← → switch | S = save")
    clock.tick(30)

pygame.quit()
