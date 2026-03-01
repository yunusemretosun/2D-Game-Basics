"""Server-side entity dataclasses and map utilities."""
import random
from dataclasses import dataclass, field
from src.constants import (
    ASSETS_DIR, PLAYER_MAX_HP, STARTING_COINS,
    POWER_UP_LIFETIME, DROPPED_WEAPON_LIFE,
)

# ── Map loading ───────────────────────────────────────────────────────────────
_MAP_PATH = ASSETS_DIR / "maps" / "map.txt"
_TILE_SZ  = 16


def _load_map():
    try:
        with open(_MAP_PATH) as f:
            return [ln.rstrip("\n") for ln in f if ln.rstrip("\n")]
    except FileNotFoundError:
        return []


_GAME_MAP = _load_map()
_MAP_ROWS = len(_GAME_MAP)
_MAP_COLS = max((len(r) for r in _GAME_MAP), default=0)


def _tile_solid(col: int, row: int) -> bool:
    if row < 0 or row >= _MAP_ROWS or col < 0:
        return True
    row_str = _GAME_MAP[row]
    return col < len(row_str) and row_str[col] != "0"


# All tiles that are solid with empty tile directly above → valid spawn floor
_VALID_FLOOR = [
    (c * _TILE_SZ, r * _TILE_SZ)
    for r in range(1, _MAP_ROWS)
    for c in range(_MAP_COLS)
    if _tile_solid(c, r) and not _tile_solid(c, r - 1)
]


def _rand_spawn(entity_height: int):
    if not _VALID_FLOOR:
        return 100.0, 100.0
    x, floor_y = random.choice(_VALID_FLOOR)
    return float(x), float(floor_y - entity_height)


def rand_player_pos():
    return _rand_spawn(13)


def rand_powerup_pos():
    return _rand_spawn(10)


# ── Entity dataclasses ────────────────────────────────────────────────────────
@dataclass
class PlayerState:
    player_id:      int
    name:           str
    team_id:        int   = -1
    x:              float = 100.0
    y:              float = 100.0
    vx:             float = 0.0
    vy:             float = 0.0
    on_ground:      bool  = False
    facing:         str   = "right"
    alive:          bool  = True
    hp:             int   = PLAYER_MAX_HP
    respawn_timer:  float = 0.0
    ready:          bool  = False
    shield_until:   float = 0.0
    weapon:         str   = "pistol"
    coins:          int   = STARTING_COINS
    reload_until:   float = 0.0   # server timestamp when next shot is allowed


@dataclass
class Projectile:
    proj_id:   int
    owner_id:  int
    team_id:   int
    x:         float
    y:         float
    vx:        float
    vy:        float
    lifetime:  float = 3.0
    damage:    int   = 20
    weapon_id: str   = "pistol"


@dataclass
class PowerUp:
    pu_id:          int
    pu_type:        str
    spawn_x:        float
    spawn_y:        float
    active:         bool  = True
    respawn_timer:  float = 0.0
    lifetime_timer: float = POWER_UP_LIFETIME


@dataclass
class DroppedWeapon:
    drop_id:   int
    weapon_id: str
    x:         float
    y:         float
    lifetime:  float = DROPPED_WEAPON_LIFE
