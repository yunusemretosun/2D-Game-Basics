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
PLAYER_W, PLAYER_H = 5, 13

# ── Teams ─────────────────────────────────────────────────────────────────────
TEAM_COLORS = [
    [220, 60,  60],
    [60,  100, 220],
    [60,  200, 60],
    [220, 180, 50],
    [180, 60,  220],
    [60,  200, 200],
]
TEAM_NAMES  = ["Red", "Blue", "Green", "Yellow", "Purple", "Cyan"]

# Initial team spawn positions (before random respawn kicks in)
TEAM_SPAWN_AREAS = {
    0: [(48, 248), (64, 248), (80, 248)],
    1: [(896, 248), (880, 248), (864, 248)],
    2: [(240, 212), (256, 212), (272, 212)],
}

# ── Shop ──────────────────────────────────────────────────────────────────────
SHOP_X      = 464
SHOP_Y      = 256
SHOP_RADIUS = 55

# ── Economy ───────────────────────────────────────────────────────────────────
STARTING_COINS      = 30
KILL_COIN_REWARD    = 15
DROPPED_WEAPON_LIFE = 20.0   # seconds before uncollected weapon disappears

# ── Weapons ───────────────────────────────────────────────────────────────────
# fire_mode: "semi" = one shot per key press | "auto" = hold to fire
# bullet lifetime = range_px / (bullet_speed * 60)  (matches server tick math)
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

# (trail_length, line_width) for draw_bullet
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
WINDOW_SIZE = (800, 600)
DISPLAY_SIZE = (400, 300)
