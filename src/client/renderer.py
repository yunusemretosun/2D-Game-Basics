"""All draw_* functions for the game client."""
import time
import pygame

from src.constants import (
    POWER_UP_LIFETIME, DROPPED_WEAPON_LIFE,
    WEAPON_COLORS, WEAPON_BULLET_SIZE,
    PU_COLORS, PU_LABELS, PU_FULL_NAMES,
    TEAM_COLORS, TEAM_NAMES,
    WEAPONS, WEAPON_COLORS,
)
import src.client.assets as assets


# ── Player ────────────────────────────────────────────────────────────────────

def draw_player(surf: pygame.Surface, x: int, y: int,
                color: tuple, alpha: int = 160) -> None:
    surf.blit(assets.player_img, (x, y))
    tint = pygame.Surface(assets.player_img.get_size(), pygame.SRCALPHA)
    tint.fill((*color, alpha))
    surf.blit(tint, (x, y), special_flags=pygame.BLEND_RGBA_MULT)


def draw_hp_bar(surf: pygame.Surface, x: int, y: int,
                hp: int, max_hp: int, color: tuple) -> None:
    bar_w, bar_h = 20, 3
    bx, by = x - bar_w // 2 + 2, y - 5
    pygame.draw.rect(surf, (60, 60, 60), (bx, by, bar_w, bar_h))
    fill_w = int(bar_w * max(0, hp) / max_hp)
    if fill_w > 0:
        if hp > max_hp * 0.5:
            bar_col = (0, 200, 0)
        elif hp > max_hp * 0.25:
            bar_col = (220, 180, 0)
        else:
            bar_col = (220, 40, 40)
        pygame.draw.rect(surf, bar_col, (bx, by, fill_w, bar_h))


def draw_shield_aura(surf: pygame.Surface, x: int, y: int) -> None:
    t = time.time()
    alpha = int(120 + 80 * abs(((t * 4) % 2) - 1))
    aura = pygame.Surface((26, 28), pygame.SRCALPHA)
    pygame.draw.ellipse(aura, (0, 180, 255, alpha), (0, 0, 26, 28), 2)
    surf.blit(aura, (x - 8, y - 6))


# ── Power-ups ─────────────────────────────────────────────────────────────────

def draw_power_up(surf: pygame.Surface, x: int, y: int,
                  pu_type: str, lifetime: float = POWER_UP_LIFETIME) -> None:
    sprite = assets.powerup_imgs.get(pu_type)
    if sprite:
        surf.blit(sprite, (x, y))
    else:
        color  = PU_COLORS.get(pu_type, (255, 255, 255))
        t      = time.time()
        pulse  = int(abs(((t * 3) % 2) - 1) * 2)
        pygame.draw.circle(surf, color, (x + 5, y + 5), 6 + pulse)
        pygame.draw.circle(surf, (255, 255, 255), (x + 5, y + 5), 6 + pulse, 1)
        label  = PU_LABELS.get(pu_type, "?")
        lbl    = assets.font_small.render(label, True, (0, 0, 0))
        surf.blit(lbl, (x + 5 - lbl.get_width() // 2, y + 5 - lbl.get_height() // 2))

    # Lifetime bar
    if 0 < lifetime < POWER_UP_LIFETIME:
        frac = max(0.0, lifetime / POWER_UP_LIFETIME)
        if frac < 0.3:
            bar_col = (255, 60, 60)
        elif frac < 0.6:
            bar_col = (255, 200, 0)
        else:
            bar_col = (150, 255, 80)
        pygame.draw.rect(surf, (50, 50, 50), (x - 1, y + 13, 12, 2))
        pygame.draw.rect(surf, bar_col, (x - 1, y + 13, max(1, int(12 * frac)), 2))


# ── Bullets ───────────────────────────────────────────────────────────────────

def draw_bullet(surf: pygame.Surface, x: float, y: float,
                vx: float, vy: float, weapon_id: str) -> None:
    """Draw a smooth elongated bullet with a trail."""
    color  = WEAPON_COLORS.get(weapon_id, (220, 220, 220))
    length, width = WEAPON_BULLET_SIZE.get(weapon_id, (6, 2))
    speed  = (vx * vx + vy * vy) ** 0.5
    if speed == 0:
        pygame.draw.circle(surf, color, (int(x), int(y)), width)
        return
    dx, dy    = vx / speed, vy / speed
    tx, ty    = int(x), int(y)
    tail_x    = int(x - dx * length)
    tail_y    = int(y - dy * length)
    trail_col = tuple(max(0, c // 3) for c in color)
    pygame.draw.line(surf, trail_col, (tx, ty), (tail_x, tail_y), max(1, width - 1))
    mid_x = int(x - dx * length // 2)
    mid_y = int(y - dy * length // 2)
    pygame.draw.line(surf, color, (tx, ty), (mid_x, mid_y), width)
    pygame.draw.circle(surf, (255, 255, 255), (tx, ty), max(1, width - 1))


# ── Dropped weapons ───────────────────────────────────────────────────────────

def draw_dropped_weapon(surf: pygame.Surface, x: int, y: int,
                        weapon_id: str, lifetime: float) -> None:
    if lifetime < 5.0 and int(time.time() * 5) % 2 == 0:
        return  # blink near expiry

    sprite = assets.weapon_imgs.get(weapon_id)
    color  = WEAPON_COLORS.get(weapon_id, (200, 200, 200))
    if sprite:
        surf.blit(sprite, (x, y))
        pygame.draw.rect(surf, color, (x, y, sprite.get_width(), sprite.get_height()), 1)
    else:
        pygame.draw.rect(surf, color, (x, y, 12, 5))
        pygame.draw.rect(surf, (255, 255, 255), (x, y, 12, 5), 1)

    wname = WEAPONS.get(weapon_id, {}).get("name", weapon_id)
    lbl   = assets.font_small.render(wname, True, color)
    surf.blit(lbl, (x + 6 - lbl.get_width() // 2, y - 10))

    # Lifetime bar
    frac    = max(0.0, lifetime / DROPPED_WEAPON_LIFE)
    bar_col = (255, 60, 60) if frac < 0.3 else (255, 200, 0) if frac < 0.6 else (100, 220, 100)
    pygame.draw.rect(surf, (40, 40, 40), (x - 1, y + 6, 14, 2))
    pygame.draw.rect(surf, bar_col, (x - 1, y + 6, max(1, int(14 * frac)), 2))


# ── Shop ──────────────────────────────────────────────────────────────────────

def draw_shop_sign(surf: pygame.Surface, wx: int, wy: int) -> None:
    """Draw the weapon shop at world-pixel (wx, wy=floor y), scroll-adjusted."""
    if assets.shop_img:
        img_w, img_h = assets.shop_img.get_size()
        surf.blit(assets.shop_img, (wx - img_w // 2, wy - img_h))
    else:
        # Fallback procedural drawing
        pygame.draw.rect(surf, (100, 70, 40), (wx - 14, wy - 28, 28, 28))
        pygame.draw.polygon(surf, (160, 50, 50),
                            [(wx - 16, wy - 28), (wx, wy - 42), (wx + 16, wy - 28)])
        pygame.draw.rect(surf, (180, 220, 255), (wx - 11, wy - 24, 8, 7))
        pygame.draw.rect(surf, (180, 220, 255), (wx + 3,  wy - 24, 8, 7))
        pygame.draw.rect(surf, (60, 35, 15),    (wx - 4,  wy - 14, 8, 14))

    sign_bg = pygame.Surface((26, 10), pygame.SRCALPHA)
    sign_bg.fill((240, 200, 40, 220))
    surf.blit(sign_bg, (wx - 13, wy - 52))
    sign_txt = assets.font_small.render("SHOP", True, (20, 20, 20))
    surf.blit(sign_txt, (wx - sign_txt.get_width() // 2, wy - 52))


def draw_shop_ui(surf: pygame.Surface, coins: int, current_weapon: str) -> None:
    """Draw the full-screen weapon shop overlay."""
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
        col_i = i % 2
        row_i = i // 2
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

        # Weapon sprite or color swatch
        sprite = assets.weapon_imgs.get(wid)
        if sprite:
            scaled = pygame.transform.scale(sprite, (18, 9))
            surf.blit(scaled, (bx + 20, by + 4))
        else:
            wcolor = WEAPON_COLORS.get(wid, (200, 200, 200))
            pygame.draw.rect(surf, wcolor, (bx + 20, by + 5, 10, 8))

        name_col  = (180, 255, 180) if is_owned else (230, 230, 230)
        name_surf = assets.font_small.render(wdata["name"], True, name_col)
        surf.blit(name_surf, (bx + 40, by + 3))
        if is_owned:
            eq = assets.font_small.render("EQUIPPED", True, (100, 220, 100))
            surf.blit(eq, (bx + 145 - eq.get_width() - 3, by + 3))

        dmg_s  = assets.font_small.render(f"DMG {wdata['damage']}",            True, (255, 110, 110))
        rng_s  = assets.font_small.render(f"RNG {wdata['range_px']}",           True, (100, 190, 255))
        rl_s   = assets.font_small.render(f"RPM {int(60/wdata['reload_time'])}", True, (210, 210, 120))
        mode_s = assets.font_small.render(wdata["fire_mode"].upper(),            True, (200, 160, 255))
        surf.blit(dmg_s,  (bx + 3, by + 18))
        surf.blit(rng_s,  (bx + 75, by + 18))
        surf.blit(rl_s,   (bx + 3,  by + 30))
        surf.blit(mode_s, (bx + 75, by + 30))

        if wdata["price"] == 0:
            price_str, price_col = "FREE", (80, 220, 80)
        else:
            price_str = f"{wdata['price']} coins"
            price_col = (255, 215, 0) if can_afford else (180, 60, 60)
        price_surf = assets.font_small.render(price_str, True, price_col)
        surf.blit(price_surf, (bx + 3, by + 44))


# ── Lobby ─────────────────────────────────────────────────────────────────────

def draw_lobby(surf: pygame.Surface, num_teams: int, my_team_id: int,
               my_ready: bool, lobby_data: dict | None):
    """Draw the team-selection lobby screen.

    Returns (team_boxes, ready_btn) as pygame.Rect objects.
    """
    surf.fill((30, 30, 50))
    title = assets.font_big.render("TEAM SELECTION", True, (255, 255, 255))
    surf.blit(title, (200 - title.get_width() // 2, 15))

    box_w, box_h = 110, 150
    start_x = 200 - (num_teams * (box_w + 10)) // 2
    team_boxes = []
    for t in range(num_teams):
        bx = start_x + t * (box_w + 10)
        by = 50
        team_boxes.append(pygame.Rect(bx, by, box_w, box_h))
        color        = tuple(TEAM_COLORS[t % len(TEAM_COLORS)])
        border_color = (255, 255, 255) if my_team_id == t else (100, 100, 100)
        pygame.draw.rect(surf, (40, 40, 60),   (bx, by, box_w, box_h))
        pygame.draw.rect(surf, border_color,   (bx, by, box_w, box_h), 2)
        name = assets.font_med.render(TEAM_NAMES[t % len(TEAM_NAMES)], True, color)
        surf.blit(name, (bx + box_w // 2 - name.get_width() // 2, by + 5))
        member_y = by + 25
        if lobby_data:
            for pinfo in lobby_data.get("players", {}).values():
                if pinfo.get("team_id") == t:
                    mark = " [OK]" if pinfo.get("ready") else ""
                    txt  = assets.font_small.render(f"{pinfo.get('name', '?')}{mark}", True, (200, 200, 200))
                    surf.blit(txt, (bx + 5, member_y))
                    member_y += 12

    ready_color = (0, 180, 0) if my_ready else (120, 120, 120)
    ready_text  = "READY!" if my_ready else "Click to Ready"
    if my_team_id < 0:
        ready_text, ready_color = "Select a team first", (80, 80, 80)

    ready_btn = pygame.Rect(200 - 70, 220, 140, 30)
    pygame.draw.rect(surf, ready_color, ready_btn, border_radius=4)
    pygame.draw.rect(surf, (200, 200, 200), ready_btn, 1, border_radius=4)
    rt = assets.font_med.render(ready_text, True, (255, 255, 255))
    surf.blit(rt, (ready_btn.centerx - rt.get_width() // 2,
                   ready_btn.centery - rt.get_height() // 2))

    inst = assets.font_small.render(
        "Click a team to join, then press Ready. Game starts when all players are ready.",
        True, (180, 180, 180))
    surf.blit(inst, (200 - inst.get_width() // 2, 260))

    pcount = len(lobby_data.get("players", {})) if lobby_data else 0
    pc_txt = assets.font_small.render(f"Players in lobby: {pcount}", True, (150, 150, 150))
    surf.blit(pc_txt, (200 - pc_txt.get_width() // 2, 275))

    return team_boxes, ready_btn
