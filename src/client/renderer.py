"""All draw_* functions and the particle system."""
import math
import random
import time
import pygame

from src.constants import (
    POWER_UP_LIFETIME, DROPPED_WEAPON_LIFE,
    WEAPON_COLORS, WEAPON_BULLET_SIZE,
    PU_COLORS, PU_LABELS, PU_FULL_NAMES,
    TEAM_COLORS, TEAM_NAMES,
    WEAPONS, PLAYER_W, PLAYER_H,
)
import src.client.assets as assets


# ─────────────────────────────────────────────────────────────────────────────
#  Particle system
# ─────────────────────────────────────────────────────────────────────────────
class Particle:
    __slots__ = ('x', 'y', 'vx', 'vy', 'life', 'max_life', 'color', 'size')

    def __init__(self, x, y, vx, vy, life, color, size):
        self.x = x; self.y = y
        self.vx = vx; self.vy = vy
        self.life = self.max_life = life
        self.color = color
        self.size = size

    def update(self, dt):
        self.x  += self.vx * dt * 60
        self.y  += self.vy * dt * 60
        self.vy += 0.08          # gentle gravity
        self.life -= dt
        return self.life > 0

    def draw(self, surf, scroll):
        frac = max(0.0, self.life / self.max_life)
        sx, sy = int(self.x) - scroll[0], int(self.y) - scroll[1]
        sz = max(1, int(self.size * frac))
        col = tuple(int(c * frac) for c in self.color)
        pygame.draw.circle(surf, col, (sx, sy), sz)


def spawn_hit_sparks(particles: list, x, y, color, count=6):
    """Small coloured sparks on bullet impact."""
    for _ in range(count):
        angle = random.uniform(0, math.tau)
        speed = random.uniform(0.5, 2.5)
        particles.append(Particle(
            x, y,
            math.cos(angle) * speed, math.sin(angle) * speed,
            random.uniform(0.2, 0.5),
            color, random.randint(1, 2),
        ))


def spawn_death_explosion(particles: list, x, y, color, count=20):
    """Larger explosion particles on death."""
    for _ in range(count):
        angle = random.uniform(0, math.tau)
        speed = random.uniform(0.8, 4.0)
        particles.append(Particle(
            x, y,
            math.cos(angle) * speed, math.sin(angle) * speed,
            random.uniform(0.5, 1.2),
            color, random.randint(2, 5),
        ))
    # white flash ring
    for _ in range(8):
        angle = random.uniform(0, math.tau)
        speed = random.uniform(3.0, 5.0)
        particles.append(Particle(
            x, y,
            math.cos(angle) * speed, math.sin(angle) * speed,
            0.25, (255, 255, 220), 3,
        ))


def spawn_coin_burst(particles: list, x, y, count=8):
    """Gold coin burst when breakable object destroyed."""
    for _ in range(count):
        angle = random.uniform(0, math.tau)
        speed = random.uniform(1.0, 3.5)
        particles.append(Particle(
            x, y,
            math.cos(angle) * speed, math.sin(angle) * speed - 1.5,
            random.uniform(0.6, 1.0),
            (255, 215, 0), random.randint(2, 4),
        ))


def update_particles(particles: list, dt: float) -> None:
    particles[:] = [p for p in particles if p.update(dt)]


def draw_particles(surf: pygame.Surface, particles: list, scroll: list) -> None:
    for p in particles:
        p.draw(surf, scroll)


# ─────────────────────────────────────────────────────────────────────────────
#  Background
# ─────────────────────────────────────────────────────────────────────────────
def draw_background(surf: pygame.Surface, scroll: list) -> None:
    """Multi-layer parallax background: sky gradient, mountains, clouds."""
    w, h = surf.get_size()

    # Sky gradient (top=dark blue, bottom=light blue)
    for y in range(h):
        frac = y / h
        r = int(30  + frac * 115)
        g = int(80  + frac * 160)
        b = int(140 + frac * 110)
        pygame.draw.line(surf, (r, g, b), (0, y), (w, y))

    # Distant mountains (slowest parallax – 0.1)
    _draw_mountains(surf, scroll[0] * 0.08, scroll[1] * 0.05,
                    (50, 80, 110), 3, h)

    # Nearer hills (0.2)
    _draw_mountains(surf, scroll[0] * 0.18, scroll[1] * 0.10,
                    (40, 110, 80), 2, h)

    # Clouds
    cloud_data = [
        (80,  30, 50, 18),
        (220, 20, 70, 22),
        (380, 45, 55, 15),
        (500, 15, 90, 25),
        (650, 35, 60, 20),
        (800, 25, 75, 17),
    ]
    for cx, cy, cw, cr in cloud_data:
        px = int(cx - scroll[0] * 0.12)
        py = int(cy - scroll[1] * 0.06)
        _draw_cloud(surf, px, py, cw, cr)


def _draw_mountains(surf, ox, oy, color, peak_count, h):
    w = surf.get_width()
    for i in range(peak_count + 1):
        bx = int(ox) + i * (w // peak_count) - 40
        by = h - 60
        px = bx + (w // peak_count) // 2
        py = by - random.randint(55, 85) if False else by - (65 + i * 20)
        pygame.draw.polygon(surf, color, [
            (bx, h), (px, py), (bx + w // peak_count, h)
        ])


def _draw_cloud(surf, x, y, w, r):
    col = (240, 248, 255)
    for dx in range(-w // 2, w // 2 + 1, r // 2):
        radius = r - abs(dx) // 4
        if radius > 0:
            pygame.draw.circle(surf, col, (x + dx, y), radius)


# ─────────────────────────────────────────────────────────────────────────────
#  Player
# ─────────────────────────────────────────────────────────────────────────────
def _get_player_sprite(team_id: int, moving: bool, anim_timer: float, facing: str):
    """Return the correct sprite surface for the current animation state."""
    if moving:
        frames = assets.team_run.get(team_id, [])
        fi = int(anim_timer * 8) % max(len(frames), 1)
        spr = frames[fi] if fi < len(frames) else None
    else:
        frames = assets.team_idle.get(team_id, [])
        fi = int(anim_timer * 3) % max(len(frames), 1)
        spr = frames[fi] if fi < len(frames) else None

    if spr is None:
        spr = assets.player_img
    return spr, facing == "left"


def draw_player(surf: pygame.Surface, x: int, y: int,
                team_id: int, moving: bool, anim_timer: float,
                facing: str = "right", flash: float = 0.0) -> None:
    """Draw an animated player sprite with optional hit-flash."""
    spr, flip = _get_player_sprite(team_id, moving, anim_timer, facing)
    if spr is None:
        pygame.draw.rect(surf, TEAM_COLORS[team_id % len(TEAM_COLORS)], (x, y, PLAYER_W, PLAYER_H))
        return

    if flip:
        spr = pygame.transform.flip(spr, True, False)

    surf.blit(spr, (x, y))

    # Hit-flash: white overlay fades out
    if flash > 0:
        alpha = int(min(255, flash * 400))
        flash_surf = pygame.Surface(spr.get_size(), pygame.SRCALPHA)
        flash_surf.fill((255, 255, 255, alpha))
        surf.blit(flash_surf, (x, y), special_flags=pygame.BLEND_RGBA_ADD)


def draw_dead_player(surf: pygame.Surface, x: int, y: int, team_id: int) -> None:
    """Draw a fallen / ghost player."""
    spr = assets.team_dead.get(team_id)
    if spr:
        surf.blit(spr, (x, y - 4))
    else:
        ghost = pygame.Surface((PLAYER_W, PLAYER_H), pygame.SRCALPHA)
        col   = TEAM_COLORS[team_id % len(TEAM_COLORS)]
        ghost.fill((*col, 55))
        surf.blit(ghost, (x, y))


def draw_hp_bar(surf: pygame.Surface, x: int, y: int,
                hp: int, max_hp: int, team_id: int) -> None:
    bw, bh = 20, 3
    bx, by = x - bw // 2 + PLAYER_W // 2, y - 5
    pygame.draw.rect(surf, (50, 50, 50), (bx, by, bw, bh))
    fw = int(bw * max(0, hp) / max_hp)
    if fw:
        frac = hp / max_hp
        col  = (0, 200, 0) if frac > 0.5 else (220, 180, 0) if frac > 0.25 else (220, 40, 40)
        pygame.draw.rect(surf, col, (bx, by, fw, bh))


def draw_shield_aura(surf: pygame.Surface, x: int, y: int) -> None:
    t     = time.time()
    alpha = int(100 + 80 * abs(((t * 4) % 2) - 1))
    aura  = pygame.Surface((PLAYER_W + 10, PLAYER_H + 10), pygame.SRCALPHA)
    pygame.draw.ellipse(aura, (0, 180, 255, alpha), (0, 0, PLAYER_W + 10, PLAYER_H + 10), 2)
    surf.blit(aura, (x - 5, y - 5))


# ─────────────────────────────────────────────────────────────────────────────
#  Power-ups
# ─────────────────────────────────────────────────────────────────────────────
def draw_power_up(surf: pygame.Surface, x: int, y: int,
                  pu_type: str, lifetime: float = POWER_UP_LIFETIME) -> None:
    sprite = assets.powerup_imgs.get(pu_type)
    color  = PU_COLORS.get(pu_type, (255, 255, 255))

    if sprite:
        t     = time.time()
        bob_y = int(math.sin(t * 3) * 2)
        surf.blit(sprite, (x, y + bob_y))
    else:
        t     = time.time()
        pulse = int(abs(((t * 3) % 2) - 1) * 2)
        pygame.draw.circle(surf, color, (x + 5, y + 5), 6 + pulse)
        pygame.draw.circle(surf, (255, 255, 255), (x + 5, y + 5), 6 + pulse, 1)
        lbl = assets.font_small.render(PU_LABELS.get(pu_type, "?"), True, (0, 0, 0))
        surf.blit(lbl, (x + 5 - lbl.get_width() // 2, y + 5 - lbl.get_height() // 2))

    # Lifetime bar
    if 0 < lifetime < POWER_UP_LIFETIME:
        frac    = max(0.0, lifetime / POWER_UP_LIFETIME)
        bar_col = (255, 60, 60) if frac < 0.3 else (255, 200, 0) if frac < 0.6 else (150, 255, 80)
        pygame.draw.rect(surf, (50, 50, 50), (x - 1, y + 13, 12, 2))
        pygame.draw.rect(surf, bar_col, (x - 1, y + 13, max(1, int(12 * frac)), 2))


# ─────────────────────────────────────────────────────────────────────────────
#  Bullets
# ─────────────────────────────────────────────────────────────────────────────
def draw_bullet(surf: pygame.Surface, x: float, y: float,
                vx: float, vy: float, weapon_id: str) -> None:
    color        = WEAPON_COLORS.get(weapon_id, (220, 220, 220))
    length, width = WEAPON_BULLET_SIZE.get(weapon_id, (6, 2))
    speed        = (vx * vx + vy * vy) ** 0.5
    if speed == 0:
        pygame.draw.circle(surf, color, (int(x), int(y)), width)
        return
    dx, dy   = vx / speed, vy / speed
    tx, ty   = int(x), int(y)
    tail_col = tuple(max(0, c // 3) for c in color)
    pygame.draw.line(surf, tail_col,
                     (tx, ty), (int(x - dx * length), int(y - dy * length)),
                     max(1, width - 1))
    pygame.draw.line(surf, color,
                     (tx, ty), (int(x - dx * length // 2), int(y - dy * length // 2)),
                     width)
    pygame.draw.circle(surf, (255, 255, 255), (tx, ty), max(1, width - 1))


# ─────────────────────────────────────────────────────────────────────────────
#  Dropped weapons
# ─────────────────────────────────────────────────────────────────────────────
def draw_dropped_weapon(surf: pygame.Surface, x: int, y: int,
                        weapon_id: str, lifetime: float,
                        near: bool = False) -> None:
    """Draw a dropped weapon as a small circle containing the weapon sprite.

    x, y are the top-left of the original player rect; we centre the icon
    at (x + PLAYER_W//2, y + PLAYER_H//2).
    """
    cx = x + PLAYER_W // 2
    cy = y + PLAYER_H // 2

    # Blink when about to despawn
    if lifetime < 5.0 and int(time.time() * 5) % 2 == 0:
        return

    color  = WEAPON_COLORS.get(weapon_id, (200, 200, 200))
    RADIUS = 9

    # Dark filled circle + coloured border
    pygame.draw.circle(surf, (20, 20, 35), (cx, cy), RADIUS)
    border_col = (255, 240, 80) if near else color
    pygame.draw.circle(surf, border_col, (cx, cy), RADIUS, 2)

    # Weapon sprite scaled to fit inside the circle
    sprite = assets.weapon_imgs.get(weapon_id)
    if sprite:
        sw, sh = sprite.get_size()
        inner  = (RADIUS - 2) * 2
        scale  = min(inner / max(sw, 1), inner / max(sh, 1))
        nw     = max(1, int(sw * scale))
        nh     = max(1, int(sh * scale))
        scaled = pygame.transform.scale(sprite, (nw, nh))
        surf.blit(scaled, (cx - nw // 2, cy - nh // 2))

    # [E] hint floats above the circle, only shown when player is close
    if near:
        hint = assets.font_small.render("[E]", True, (255, 240, 80))
        surf.blit(hint, (cx - hint.get_width() // 2, cy - RADIUS - 10))

    # Thin lifetime bar beneath the circle
    frac    = max(0.0, lifetime / DROPPED_WEAPON_LIFE)
    bar_w   = RADIUS * 2
    bar_col = (255, 60, 60) if frac < 0.3 else (255, 200, 0) if frac < 0.6 else (80, 200, 80)
    pygame.draw.rect(surf, (40, 40, 40), (cx - RADIUS, cy + RADIUS + 2, bar_w, 2))
    pygame.draw.rect(surf, bar_col, (cx - RADIUS, cy + RADIUS + 2, max(1, int(bar_w * frac)), 2))


# ─────────────────────────────────────────────────────────────────────────────
#  Breakable objects
# ─────────────────────────────────────────────────────────────────────────────
def draw_breakable_object(surf: pygame.Surface, x: int, y: int,
                          obj_type: str, hp: int, max_hp: int) -> None:
    sprite = assets.object_imgs.get(obj_type)
    if sprite:
        sw, sh = sprite.get_size()
        # Draw sprite so its base aligns with y
        surf.blit(sprite, (x - sw // 2, y - sh))
        # Damage cracks overlay (darker when more damaged)
        frac = hp / max_hp
        if frac < 0.7:
            crack = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
            alpha = int((1 - frac) * 180)
            crack.fill((20, 10, 0, alpha))
            surf.blit(crack, (x - sw // 2, y - sh), special_flags=pygame.BLEND_RGBA_MULT)
    else:
        # Fallback rectangle
        sw = 16
        sh = {"tree": 32, "barrel": 16, "crate": 16}.get(obj_type, 16)
        col = {"tree": (60, 150, 60), "barrel": (140, 80, 30), "crate": (160, 120, 50)}.get(obj_type, (150, 150, 150))
        pygame.draw.rect(surf, col, (x - sw // 2, y - sh, sw, sh))

    # HP bar above object
    if max_hp > 1:
        bw = 20
        bx = x - bw // 2
        by = y - {"tree": 34, "barrel": 18, "crate": 18}.get(obj_type, 18)
        frac = max(0.0, hp / max_hp)
        bar_col = (255, 60, 60) if frac < 0.4 else (255, 200, 0) if frac < 0.7 else (80, 220, 80)
        pygame.draw.rect(surf, (40, 40, 40), (bx, by, bw, 3))
        pygame.draw.rect(surf, bar_col, (bx, by, max(1, int(bw * frac)), 3))


# ─────────────────────────────────────────────────────────────────────────────
#  Shop
# ─────────────────────────────────────────────────────────────────────────────
def draw_shop_sign(surf: pygame.Surface, wx: int, wy: int) -> None:
    if assets.shop_img:
        iw, ih = assets.shop_img.get_size()
        surf.blit(assets.shop_img, (wx - iw // 2, wy - ih))
    else:
        pygame.draw.rect(surf, (100, 70, 40), (wx - 14, wy - 28, 28, 28))
        pygame.draw.polygon(surf, (160, 50, 50),
                            [(wx - 16, wy - 28), (wx, wy - 42), (wx + 16, wy - 28)])
        pygame.draw.rect(surf, (180, 220, 255), (wx - 11, wy - 24, 8, 7))
        pygame.draw.rect(surf, (180, 220, 255), (wx + 3,  wy - 24, 8, 7))
        pygame.draw.rect(surf, (60, 35, 15),    (wx - 4,  wy - 14, 8, 14))

    sign_bg = pygame.Surface((28, 10), pygame.SRCALPHA)
    sign_bg.fill((240, 200, 40, 220))
    surf.blit(sign_bg, (wx - 14, wy - 54))
    sign_txt = assets.font_small.render("SHOP", True, (20, 20, 20))
    surf.blit(sign_txt, (wx - sign_txt.get_width() // 2, wy - 54))


def draw_shop_ui(surf: pygame.Surface, coins: int, current_weapon: str) -> None:
    panel = pygame.Surface((310, 210), pygame.SRCALPHA)
    panel.fill((10, 10, 30, 220))
    ox, oy = 45, 45
    surf.blit(panel, (ox, oy))
    pygame.draw.rect(surf, (200, 160, 40), (ox, oy, 310, 210), 2)

    title = assets.font_med.render("WEAPON SHOP", True, (255, 200, 40))
    surf.blit(title, (ox + 155 - title.get_width() // 2, oy + 5))

    coin_surf  = assets.font_small.render(f"Coins: {coins}", True, (255, 215, 0))
    close_hint = assets.font_small.render("[E] Close", True, (160, 160, 160))
    surf.blit(coin_surf,  (ox + 5,  oy + 22))
    surf.blit(close_hint, (ox + 305 - close_hint.get_width(), oy + 22))

    for i, (wid, wdata) in enumerate(WEAPONS.items()):
        col_i = i % 2;  row_i = i // 2
        bx = ox + 8   + col_i * 153
        by = oy + 38  + row_i * 82

        is_owned   = (wid == current_weapon)
        can_afford = coins >= wdata["price"]

        bg     = (30, 80, 30) if is_owned else (25, 25, 50)
        border = (100, 220, 100) if is_owned else ((200, 200, 60) if can_afford else (80, 80, 80))
        pygame.draw.rect(surf, bg,     (bx, by, 145, 74), border_radius=4)
        pygame.draw.rect(surf, border, (bx, by, 145, 74), 1, border_radius=4)

        key_surf = assets.font_small.render(f"[{i+1}]", True, (180, 180, 180))
        surf.blit(key_surf, (bx + 3, by + 3))

        sprite = assets.weapon_imgs.get(wid)
        if sprite:
            scaled = pygame.transform.scale(sprite, (18, 9))
            surf.blit(scaled, (bx + 20, by + 4))
        else:
            wcolor = WEAPON_COLORS.get(wid, (200, 200, 200))
            pygame.draw.rect(surf, wcolor, (bx + 20, by + 5, 10, 8))

        nc = (180, 255, 180) if is_owned else (230, 230, 230)
        ns = assets.font_small.render(wdata["name"], True, nc)
        surf.blit(ns, (bx + 40, by + 3))
        if is_owned:
            eq = assets.font_small.render("EQUIPPED", True, (100, 220, 100))
            surf.blit(eq, (bx + 145 - eq.get_width() - 3, by + 3))

        surf.blit(assets.font_small.render(f"DMG {wdata['damage']}",            True, (255,110,110)), (bx+3,  by+18))
        surf.blit(assets.font_small.render(f"RNG {wdata['range_px']}",           True, (100,190,255)), (bx+75, by+18))
        surf.blit(assets.font_small.render(f"RPM {int(60/wdata['reload_time'])}", True, (210,210,120)), (bx+3,  by+30))
        surf.blit(assets.font_small.render(wdata["fire_mode"].upper(),            True, (200,160,255)), (bx+75, by+30))

        if wdata["price"] == 0:
            pstr, pcol = "FREE", (80, 220, 80)
        else:
            pstr = f"{wdata['price']} coins"
            pcol = (255, 215, 0) if can_afford else (180, 60, 60)
        surf.blit(assets.font_small.render(pstr, True, pcol), (bx + 3, by + 44))


# ─────────────────────────────────────────────────────────────────────────────
#  Lobby
# ─────────────────────────────────────────────────────────────────────────────
def draw_lobby(surf: pygame.Surface, num_teams: int, my_team_id: int,
               my_ready: bool, lobby_data: dict | None):
    surf.fill((30, 30, 50))
    title = assets.font_big.render("TEAM SELECTION", True, (255, 255, 255))
    surf.blit(title, (200 - title.get_width() // 2, 15))

    bw, bh = 110, 150
    sx = 200 - (num_teams * (bw + 10)) // 2
    team_boxes = []
    for t in range(num_teams):
        bx = sx + t * (bw + 10);  by = 50
        team_boxes.append(pygame.Rect(bx, by, bw, bh))
        color  = tuple(TEAM_COLORS[t % len(TEAM_COLORS)])
        border = (255, 255, 255) if my_team_id == t else (100, 100, 100)
        pygame.draw.rect(surf, (40, 40, 60),  (bx, by, bw, bh))
        pygame.draw.rect(surf, border,        (bx, by, bw, bh), 2)
        nm = assets.font_med.render(TEAM_NAMES[t % len(TEAM_NAMES)], True, color)
        surf.blit(nm, (bx + bw // 2 - nm.get_width() // 2, by + 5))
        my = by + 25
        if lobby_data:
            for pinfo in lobby_data.get("players", {}).values():
                if pinfo.get("team_id") == t:
                    mark = " [OK]" if pinfo.get("ready") else ""
                    txt  = assets.font_small.render(f"{pinfo.get('name','?')}{mark}", True, (200,200,200))
                    surf.blit(txt, (bx + 5, my));  my += 12

    ready_color = (0, 180, 0) if my_ready else (120, 120, 120)
    ready_text  = ("READY!" if my_ready else
                   ("Select a team first" if my_team_id < 0 else "Click to Ready"))
    if my_team_id < 0:
        ready_color = (80, 80, 80)

    rbtn = pygame.Rect(200 - 70, 220, 140, 30)
    pygame.draw.rect(surf, ready_color, rbtn, border_radius=4)
    pygame.draw.rect(surf, (200, 200, 200), rbtn, 1, border_radius=4)
    rt = assets.font_med.render(ready_text, True, (255, 255, 255))
    surf.blit(rt, (rbtn.centerx - rt.get_width() // 2, rbtn.centery - rt.get_height() // 2))

    inst = assets.font_small.render(
        "Click a team, then click Ready. Game starts when all players are ready.",
        True, (180, 180, 180))
    surf.blit(inst, (200 - inst.get_width() // 2, 260))

    pc = len(lobby_data.get("players", {})) if lobby_data else 0
    surf.blit(assets.font_small.render(f"Players: {pc}", True, (150,150,150)),
              (200 - 20, 275))

    return team_boxes, rbtn


# ─────────────────────────────────────────────────────────────────────────────
#  Score HUD
# ─────────────────────────────────────────────────────────────────────────────
def draw_score_hud(surf: pygame.Surface, team_kills: dict,
                   my_team_id: int, kill_limit: int) -> None:
    """Draw kill scores at top-right."""
    x, y = 395, 3
    for team_id_str, kills in sorted(team_kills.items(), key=lambda kv: -kv[1]):
        tid   = int(team_id_str)
        color = tuple(TEAM_COLORS[tid % len(TEAM_COLORS)])
        if tid == my_team_id:
            color = tuple(min(255, c + 40) for c in color)
        name  = TEAM_NAMES[tid % len(TEAM_NAMES)]
        txt   = assets.font_small.render(f"{name}: {kills}/{kill_limit}", True, color)
        surf.blit(txt, (x - txt.get_width(), y))
        y += 11
