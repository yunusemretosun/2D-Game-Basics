"""Asset loading for the game client.

All images and the map are loaded once at import time.
Other modules import the already-loaded surfaces from here.
"""
import pygame
from src.constants import ASSETS_DIR, POWER_UP_TYPES, WEAPONS

# ── Tile images ───────────────────────────────────────────────────────────────
grass_img: pygame.Surface = None   # 16×16
dirt_img:  pygame.Surface = None   # 16×16

# ── Player sprite ─────────────────────────────────────────────────────────────
player_img: pygame.Surface = None  # 5×13

# ── Weapon sprites (12×6) ─────────────────────────────────────────────────────
weapon_imgs: dict[str, pygame.Surface] = {}

# ── Power-up sprites (16×16) ──────────────────────────────────────────────────
powerup_imgs: dict[str, pygame.Surface] = {}

# ── Shop sprite (32×48) ───────────────────────────────────────────────────────
shop_img: pygame.Surface = None

# ── Parsed map ────────────────────────────────────────────────────────────────
game_map: list[list[str]] = []

# ── Fonts (set after pygame.init) ─────────────────────────────────────────────
font_small: pygame.font.Font = None
font_med:   pygame.font.Font = None
font_big:   pygame.font.Font = None


def load_all() -> None:
    """Call once after pygame.init() to populate all asset globals."""
    global grass_img, dirt_img, player_img, shop_img
    global font_small, font_med, font_big

    ts = ASSETS_DIR / "tilesets"
    grass_img = pygame.image.load(str(ts / "grass.png")).convert()
    dirt_img  = pygame.image.load(str(ts / "dirt.png")).convert()

    sp = ASSETS_DIR / "sprites" / "player"
    player_img = pygame.image.load(str(sp / "player.png")).convert()
    player_img.set_colorkey((255, 255, 255))

    wp = ASSETS_DIR / "sprites" / "weapons"
    for wid in WEAPONS:
        f = wp / f"{wid}.png"
        if f.exists():
            img = pygame.image.load(str(f)).convert_alpha()
            weapon_imgs[wid] = img

    pp = ASSETS_DIR / "sprites" / "powerups"
    for pu_type in POWER_UP_TYPES:
        f = pp / f"{pu_type}.png"
        if f.exists():
            img = pygame.image.load(str(f)).convert_alpha()
            powerup_imgs[pu_type] = img

    sh = ASSETS_DIR / "sprites" / "shop" / "shop.png"
    if sh.exists():
        shop_img = pygame.image.load(str(sh)).convert_alpha()

    font_small = pygame.font.SysFont(None, 14)
    font_med   = pygame.font.SysFont(None, 20)
    font_big   = pygame.font.SysFont(None, 32)

    _load_map()


def _load_map() -> None:
    global game_map
    map_path = ASSETS_DIR / "maps" / "map.txt"
    with open(map_path, "r") as f:
        raw = f.read()
    game_map = [list(row) for row in raw.split("\n") if row]
