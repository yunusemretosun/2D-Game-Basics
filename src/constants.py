"""Shared constants for server and client."""
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"

# ── Server network ────────────────────────────────────────────────────────────
HOST        = "0.0.0.0"
PORT        = 5555
MAX_PLAYERS = 6
NUM_TEAMS   = 3
TICK_RATE   = 20

# ── Client network ────────────────────────────────────────────────────────────
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5555

# ── Player ────────────────────────────────────────────────────────────────────
PLAYER_MAX_HP    = 100
RESPAWN_DELAY    = 3.0
RESPAWN_SHIELD   = 2.0   # seconds of invincibility after respawn
PLAYER_W, PLAYER_H = 8, 16

# ── Win condition ─────────────────────────────────────────────────────────────
# First team to reach KILL_LIMIT total kills wins (or play forever if 0)
KILL_LIMIT = 15

# ── Teams ─────────────────────────────────────────────────────────────────────
TEAM_COLORS = [
    [210,  55,  55],   # Red
    [ 55, 100, 215],   # Blue
    [ 45, 185,  55],   # Green
    [210, 175,  45],   # Yellow
    [170,  55, 215],   # Purple
    [ 45, 195, 195],   # Cyan
]
TEAM_NAMES  = ["Red", "Blue", "Green", "Yellow", "Purple", "Cyan"]

TEAM_SPAWN_AREAS = {
    0: [(48, 336), (64, 336), (80, 336)],
    1: [(896, 336), (880, 336), (864, 336)],
    2: [(240, 336), (256, 336), (272, 336)],
}

# ── Tiles ─────────────────────────────────────────────────────────────────────
# 0=empty  1=dirt  2=grass  3=stone  4=wood  5=brick
TILE_SOLID = {'1', '2', '3', '4', '5'}

# ── Shop ──────────────────────────────────────────────────────────────────────
SHOP_X      = 464
SHOP_Y      = 256
SHOP_RADIUS = 60

# ── Economy ───────────────────────────────────────────────────────────────────
STARTING_COINS      = 30
KILL_COIN_REWARD    = 15
DROPPED_WEAPON_LIFE = 20.0
WEAPON_PICKUP_DELAY = 0.6    # seconds before a freshly dropped weapon can be picked up

# ── Breakable objects ─────────────────────────────────────────────────────────
# (type, world_x, world_y_base)
# y_base = TOP of the tile the object stands on = row * TILE_SZ
# Renderer draws sprites so their BASE aligns with y_base (sprite goes upward).
BREAKABLE_DEFS = [
    # Ground row 22  (tile top y = 22*16 = 352)
    ("tree",    80,   352),   # col  5
    ("tree",   208,   352),   # col 13
    ("tree",   768,   352),   # col 48
    ("tree",   928,   352),   # col 58
    # Row 19  (tile top y = 304)
    ("barrel",  64,   304),   # col  4, left wood platform
    ("barrel", 896,   304),   # col 56, right wood platform
    # Row 16 shop platform  (tile top y = 256)
    ("crate",  272,   256),   # col 17
    ("crate",  720,   256),   # col 45
    # Row 13 mid platforms  (tile top y = 208)
    ("crate",  288,   208),   # col 18
    ("crate",  656,   208),   # col 41
    # Row 10 upper-mid  (tile top y = 160)
    ("tree",   112,   160),   # col  7
    ("tree",   832,   160),   # col 52
    # Row 7 high  (tile top y = 112)
    ("barrel", 480,   112),   # col 30, center grass
    # Row 4 top  (tile top y = 64)
    ("crate",  128,    64),   # col  8
    ("crate",  800,    64),   # col 50
]

BREAKABLE_HP = {"tree": 3, "barrel": 1, "crate": 2}
BREAKABLE_COIN_RANGE = {"tree": (8, 16), "barrel": (4, 10), "crate": (6, 14)}
BREAKABLE_PROJECTILE_DAMAGE = 10   # bullets deal this much to objects

# ── Weapons ───────────────────────────────────────────────────────────────────
WEAPONS = {
    "pistol": {
        "name": "Pistol", "fire_mode": "semi",
        "damage": 20, "range_px": 240, "reload_time": 0.40,
        "bullet_speed": 7.0, "pellets": 1, "spread": 0,
        "price": 0, "color": [210, 210, 210],
    },
    "auto": {
        "name": "Auto", "fire_mode": "auto",
        "damage": 12, "range_px": 280, "reload_time": 0.10,
        "bullet_speed": 8.0, "pellets": 1, "spread": 0,
        "price": 50, "color": [255, 200, 50],
    },
    "semi_auto": {
        "name": "Semi-Auto", "fire_mode": "semi",
        "damage": 28, "range_px": 320, "reload_time": 0.30,
        "bullet_speed": 9.0, "pellets": 1, "spread": 0,
        "price": 60, "color": [80, 200, 255],
    },
    "sniper": {
        "name": "Sniper", "fire_mode": "semi",
        "damage": 70, "range_px": 800, "reload_time": 1.80,
        "bullet_speed": 14.0, "pellets": 1, "spread": 0,
        "price": 80, "color": [255, 50, 50],
    },
    "shotgun": {
        "name": "Shotgun", "fire_mode": "semi",
        "damage": 18, "range_px": 130, "reload_time": 0.90,
        "bullet_speed": 6.0, "pellets": 5, "spread": 3,
        "price": 70, "color": [255, 140, 40],
    },
}

# ── Power-ups ─────────────────────────────────────────────────────────────────
POWER_UP_TYPES = ["speed", "jump", "shield", "rapid_fire", "double_jump"]

POWER_UP_DURATIONS = {
    "speed":       10.0,
    "jump":        10.0,
    "shield":       5.0,
    "rapid_fire":   8.0,
    "double_jump": 10.0,
}

POWER_UP_COLORS = {
    "speed":       [255, 215, 0],
    "jump":        [0, 220, 80],
    "shield":      [0, 180, 255],
    "rapid_fire":  [255, 80, 0],
    "double_jump": [200, 0, 255],
}

NUM_POWER_UPS         = 7
POWER_UP_RESPAWN_TIME = 15.0
POWER_UP_LIFETIME     = 12.0

# ── Client-side visual constants ──────────────────────────────────────────────
WEAPON_COLORS = {
    "pistol":    (210, 210, 210),
    "auto":      (255, 200,  50),
    "semi_auto": ( 80, 200, 255),
    "sniper":    (255,  50,  50),
    "shotgun":   (255, 140,  40),
}

WEAPON_BULLET_SIZE = {
    "pistol":    (6,  2),
    "auto":      (8,  2),
    "semi_auto": (8,  2),
    "sniper":    (14, 1),
    "shotgun":   (4,  3),
}

PU_COLORS = {
    "speed":       (255, 215, 0),
    "jump":        (0,   220, 80),
    "shield":      (0,   180, 255),
    "rapid_fire":  (255, 80,  0),
    "double_jump": (200, 0,   255),
}

PU_LABELS = {
    "speed":       "S",
    "jump":        "J",
    "shield":      "SH",
    "rapid_fire":  "RF",
    "double_jump": "DJ",
}

PU_FULL_NAMES = {
    "speed":       "SPEED x2",
    "jump":        "JUMP x2",
    "shield":      "SHIELD",
    "rapid_fire":  "RAPID FIRE",
    "double_jump": "DBL JUMP",
}

# ── Window ────────────────────────────────────────────────────────────────────
WINDOW_SIZE  = (800, 600)
DISPLAY_SIZE = (400, 300)
