"""Asset loading for the game client.

Call load_all() once after pygame.init().
"""
import pygame
from src.constants import ASSETS_DIR, POWER_UP_TYPES, WEAPONS

# ── Tile images ───────────────────────────────────────────────────────────────
grass_img: pygame.Surface = None
dirt_img:  pygame.Surface = None
stone_img: pygame.Surface = None
wood_img:  pygame.Surface = None
brick_img: pygame.Surface = None

TILE_IMGS: dict[str, pygame.Surface] = {}   # populated in load_all()

# ── Player sprites per team ───────────────────────────────────────────────────
# team_idle[team_id][frame 0-2]
# team_run[team_id][frame 0-1]
# team_dead[team_id]
team_idle: dict[int, list] = {}
team_run:  dict[int, list] = {}
team_dead: dict[int, pygame.Surface] = {}

# Fallback base sprite
player_img: pygame.Surface = None

# ── Weapon sprites ────────────────────────────────────────────────────────────
weapon_imgs: dict[str, pygame.Surface] = {}

# ── Power-up sprites ─────────────────────────────────────────────────────────
powerup_imgs: dict[str, pygame.Surface] = {}

# ── Breakable object sprites ──────────────────────────────────────────────────
object_imgs: dict[str, pygame.Surface] = {}

# ── Shop sprite ───────────────────────────────────────────────────────────────
shop_img: pygame.Surface = None

# ── Map ───────────────────────────────────────────────────────────────────────
game_map: list[list[str]] = []

# ── Fonts ─────────────────────────────────────────────────────────────────────
font_small: pygame.font.Font = None
font_med:   pygame.font.Font = None
font_big:   pygame.font.Font = None


def _load(path, alpha=True):
    if not path.exists():
        return None
    return pygame.image.load(str(path)).convert_alpha() if alpha \
        else pygame.image.load(str(path)).convert()


def load_all() -> None:
    global grass_img, dirt_img, stone_img, wood_img, brick_img, player_img, shop_img
    global font_small, font_med, font_big

    ts = ASSETS_DIR / "tilesets"
    grass_img = _load(ts / "grass.png", alpha=False) or pygame.Surface((16, 16))
    dirt_img  = _load(ts / "dirt.png",  alpha=False) or pygame.Surface((16, 16))
    stone_img = _load(ts / "stone.png", alpha=False) or pygame.Surface((16, 16))
    wood_img  = _load(ts / "wood.png",  alpha=False) or pygame.Surface((16, 16))
    brick_img = _load(ts / "brick.png", alpha=False) or pygame.Surface((16, 16))

    TILE_IMGS.update({
        '1': dirt_img,
        '2': grass_img,
        '3': stone_img,
        '4': wood_img,
        '5': brick_img,
    })

    sp = ASSETS_DIR / "sprites" / "player"

    # Team-specific sprites
    for ti in range(6):
        idle_frames = []
        for fi in range(3):
            img = _load(sp / f"team{ti}_idle_{fi}.png")
            idle_frames.append(img)
        team_idle[ti] = idle_frames

        run_frames = []
        for fi in range(2):
            img = _load(sp / f"team{ti}_run_{fi}.png")
            run_frames.append(img)
        team_run[ti] = run_frames

        dead = _load(sp / f"team{ti}_dead.png")
        team_dead[ti] = dead

    # Fallback player
    fallback = sp / "player.png"
    if fallback.exists():
        player_img = pygame.image.load(str(fallback)).convert()
        player_img.set_colorkey((255, 255, 255))

    wp = ASSETS_DIR / "sprites" / "weapons"
    for wid in WEAPONS:
        img = _load(wp / f"{wid}.png")
        if img:
            weapon_imgs[wid] = img

    pp = ASSETS_DIR / "sprites" / "powerups"
    for pu_type in POWER_UP_TYPES:
        img = _load(pp / f"{pu_type}.png")
        if img:
            powerup_imgs[pu_type] = img

    ob = ASSETS_DIR / "sprites" / "objects"
    for obj_type in ("tree", "barrel", "crate"):
        img = _load(ob / f"{obj_type}.png")
        if img:
            object_imgs[obj_type] = img

    sh = ASSETS_DIR / "sprites" / "shop" / "shop.png"
    if sh.exists():
        shop_img = pygame.image.load(str(sh)).convert_alpha()

    font_small = pygame.font.SysFont(None, 14)
    font_med   = pygame.font.SysFont(None, 20)
    font_big   = pygame.font.SysFont(None, 32)

    _load_map()


def _load_map() -> None:
    global game_map
    path = ASSETS_DIR / "maps" / "map.txt"
    with open(path) as f:
        raw = f.read()
    game_map = [list(row) for row in raw.split("\n") if row]
