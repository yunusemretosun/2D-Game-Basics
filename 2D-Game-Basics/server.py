import os
import socket
import threading
import json
import time
import random
from dataclasses import dataclass, field

HOST = "0.0.0.0"
PORT = 5555
MAX_PLAYERS = 6
NUM_TEAMS = 3
TICK_RATE = 20
RESPAWN_DELAY = 3.0
PLAYER_MAX_HP = 100
PROJECTILE_SPEED = 5.0
PROJECTILE_DAMAGE = 20
PROJECTILE_LIFETIME = 3.0

# Team 0 = left base, Team 1 = right base, Team 2 = center top
TEAM_SPAWN_AREAS = {
    0: [(48, 248), (64, 248), (80, 248)],      # far left elevated base
    1: [(896, 248), (880, 248), (864, 248)],    # far right elevated base
    2: [(240, 212), (256, 212), (272, 212)],    # center, above mid platform
}

TEAM_COLORS = [
    [220, 60,  60],
    [60,  100, 220],
    [60,  200, 60],
    [220, 180, 50],
    [180, 60,  220],
    [60,  200, 200],
]

# ── Power-up system ───────────────────────────────────────────────────────────
POWER_UP_TYPES = ["speed", "jump", "shield", "rapid_fire", "double_jump"]

POWER_UP_DURATIONS = {
    "speed":       10.0,   # 2x speed for 10s
    "jump":        10.0,   # 2x jump height for 10s
    "shield":       5.0,   # immune to damage for 5s
    "rapid_fire":   8.0,   # 3x fire rate for 8s
    "double_jump": 10.0,   # mid-air jump for 10s
}

POWER_UP_COLORS = {
    "speed":       [255, 215, 0],
    "jump":        [0, 220, 80],
    "shield":      [0, 180, 255],
    "rapid_fire":  [255, 80, 0],
    "double_jump": [200, 0, 255],
}

NUM_POWER_UPS = 7  # total power-ups on the map at once

POWER_UP_RESPAWN_TIME = 15.0  # seconds until a collected/expired power-up reappears
POWER_UP_LIFETIME     = 12.0  # seconds an active power-up stays before relocating

# ── Map parsing: find valid spawn tiles ───────────────────────────────────────
def _load_server_map():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map.txt")
    try:
        with open(path) as f:
            return [ln.rstrip('\n') for ln in f if ln.rstrip('\n')]
    except FileNotFoundError:
        return []

_GAME_MAP  = _load_server_map()
_MAP_ROWS  = len(_GAME_MAP)
_MAP_COLS  = max((len(r) for r in _GAME_MAP), default=0)
_TILE_SZ   = 16

def _tile_solid(col: int, row: int) -> bool:
    if row < 0 or row >= _MAP_ROWS or col < 0:
        return True
    row_str = _GAME_MAP[row]
    return col < len(row_str) and row_str[col] != '0'

# Every floor tile: solid tile that has an empty tile directly above it
_VALID_FLOOR = [
    (c * _TILE_SZ, r * _TILE_SZ)
    for r in range(1, _MAP_ROWS)
    for c in range(_MAP_COLS)
    if _tile_solid(c, r) and not _tile_solid(c, r - 1)
]

def _rand_spawn(entity_height: int):
    """Return (x, y) world-pixel top-left so entity stands on a valid floor tile."""
    if not _VALID_FLOOR:
        return 100.0, 100.0
    x, floor_y = random.choice(_VALID_FLOOR)
    return float(x), float(floor_y - entity_height)

def rand_player_pos():
    return _rand_spawn(13)   # player height = 13 px

def rand_powerup_pos():
    return _rand_spawn(10)   # power-up height = 10 px


@dataclass
class PlayerState:
    player_id: int
    name: str
    team_id: int = -1
    x: float = 100.0
    y: float = 100.0
    vx: float = 0.0
    vy: float = 0.0
    on_ground: bool = False
    facing: str = "right"
    alive: bool = True
    hp: int = PLAYER_MAX_HP
    respawn_timer: float = 0.0
    ready: bool = False
    shield_until: float = 0.0


@dataclass
class Projectile:
    proj_id: int
    owner_id: int
    team_id: int
    x: float
    y: float
    vx: float
    vy: float
    lifetime: float = PROJECTILE_LIFETIME


@dataclass
class PowerUp:
    pu_id: int
    pu_type: str
    spawn_x: float
    spawn_y: float
    active: bool = True
    respawn_timer: float = 0.0
    lifetime_timer: float = POWER_UP_LIFETIME  # despawn after this many seconds


class GameServer:
    def __init__(self):
        self.players: dict[int, PlayerState] = {}
        self.clients: dict[int, socket.socket] = {}
        self.projectiles: dict[int, Projectile] = {}
        self.power_ups: dict[int, PowerUp] = {}
        self.next_id: int = 0
        self.next_proj_id: int = 0
        self.lock = threading.Lock()
        self.game_over = False
        self.game_started = False

    def send_to(self, player_id: int, msg: dict) -> None:
        conn = self.clients.get(player_id)
        if conn:
            try:
                conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            except Exception:
                pass

    def broadcast(self, msg: dict) -> None:
        data = (json.dumps(msg) + "\n").encode("utf-8")
        for pid, conn in list(self.clients.items()):
            try:
                conn.sendall(data)
            except Exception:
                pass

    def get_team_counts(self) -> dict:
        counts = {}
        for p in self.players.values():
            if p.team_id >= 0:
                counts[p.team_id] = counts.get(p.team_id, 0) + 1
        return counts

    def get_lobby_info(self) -> dict:
        players_info = {}
        for pid, p in self.players.items():
            players_info[str(pid)] = {
                "name": p.name,
                "team_id": p.team_id,
                "ready": p.ready,
            }
        return {
            "type": "lobby_update",
            "players": players_info,
            "team_counts": {str(k): v for k, v in self.get_team_counts().items()},
            "game_started": self.game_started,
        }

    def check_all_ready(self) -> bool:
        if len(self.players) < 2:
            return False
        for p in self.players.values():
            if p.team_id < 0 or not p.ready:
                return False
        return True

    def start_game(self) -> None:
        self.game_started = True
        for p in self.players.values():
            spawns = TEAM_SPAWN_AREAS.get(p.team_id, TEAM_SPAWN_AREAS[0])
            team_members = [pp for pp in self.players.values()
                           if pp.team_id == p.team_id]
            idx = team_members.index(p) % len(spawns)
            sx, sy = spawns[idx]
            p.x, p.y = float(sx), float(sy)
            p.hp = PLAYER_MAX_HP
            p.alive = True
            p.shield_until = 0.0

        # Initialize power-ups at random valid positions (not inside tiles)
        shuffled_types = POWER_UP_TYPES.copy()
        random.shuffle(shuffled_types)
        for i in range(NUM_POWER_UPS):
            pu_type = shuffled_types[i % len(shuffled_types)]
            px, py = rand_powerup_pos()
            pu = PowerUp(pu_id=i, pu_type=pu_type, spawn_x=px, spawn_y=py)
            self.power_ups[i] = pu

        for p in self.players.values():
            self.send_to(p.player_id, {
                "type": "game_start",
                "spawn_x": p.x,
                "spawn_y": p.y,
            })
        print("Game started!")

    def spawn_projectile(self, owner_id: int, facing: str) -> None:
        p = self.players.get(owner_id)
        if not p or not p.alive:
            return
        pid = self.next_proj_id
        self.next_proj_id += 1
        vx = PROJECTILE_SPEED if facing == "right" else -PROJECTILE_SPEED
        proj = Projectile(
            proj_id=pid,
            owner_id=owner_id,
            team_id=p.team_id,
            x=p.x + (5 if facing == "right" else -4),
            y=p.y + 5,
            vx=vx,
            vy=0,
        )
        self.projectiles[pid] = proj
        self.broadcast({
            "type": "projectile_spawn",
            "proj_id": pid,
            "owner_id": owner_id,
            "team_id": p.team_id,
            "x": proj.x, "y": proj.y,
            "vx": proj.vx, "vy": proj.vy,
        })

    def tick_projectiles(self, dt: float) -> None:
        now = time.time()
        to_remove = []
        for pid, proj in list(self.projectiles.items()):
            proj.x += proj.vx * dt * 60
            proj.y += proj.vy * dt * 60
            proj.lifetime -= dt
            if proj.lifetime <= 0 or proj.x < -50 or proj.x > 1100 or proj.y > 500:
                to_remove.append(pid)
                continue
            for plr in list(self.players.values()):
                if plr.player_id == proj.owner_id:
                    continue
                if plr.team_id == proj.team_id:
                    continue
                if not plr.alive:
                    continue
                # Shield check
                if now < plr.shield_until:
                    continue
                if (proj.x + 4 > plr.x and proj.x < plr.x + 5 and
                        proj.y + 4 > plr.y and proj.y < plr.y + 13):
                    plr.hp -= PROJECTILE_DAMAGE
                    self.broadcast({
                        "type": "projectile_hit",
                        "proj_id": pid,
                        "victim_id": plr.player_id,
                        "damage": PROJECTILE_DAMAGE,
                        "hp": plr.hp,
                    })
                    to_remove.append(pid)
                    if plr.hp <= 0:
                        plr.alive = False
                        plr.hp = 0
                        plr.respawn_timer = RESPAWN_DELAY
                        self.broadcast({
                            "type": "player_killed",
                            "victim_id": plr.player_id,
                            "killer_id": proj.owner_id,
                        })
                        self.check_win_condition()
                    break
        for pid in to_remove:
            self.projectiles.pop(pid, None)

    def tick_power_ups(self, dt: float) -> None:
        now = time.time()
        for pu in list(self.power_ups.values()):
            if not pu.active:
                pu.respawn_timer -= dt
                if pu.respawn_timer <= 0:
                    # Reactivate at a NEW random valid position (not inside tiles)
                    pu.spawn_x, pu.spawn_y = rand_powerup_pos()
                    pu.active = True
                    pu.lifetime_timer = POWER_UP_LIFETIME
                    # Cycle to next type
                    idx = POWER_UP_TYPES.index(pu.pu_type)
                    pu.pu_type = POWER_UP_TYPES[(idx + 1) % len(POWER_UP_TYPES)]
                continue

            # Count down active lifetime; expire and relocate when it runs out
            pu.lifetime_timer -= dt
            if pu.lifetime_timer <= 0:
                pu.active = False
                pu.respawn_timer = POWER_UP_RESPAWN_TIME
                self.broadcast({"type": "powerup_expired", "pu_id": pu.pu_id})
                continue

            # Check player pickup (power-up hitbox 10x10)
            for plr in list(self.players.values()):
                if not plr.alive:
                    continue
                if (plr.x < pu.spawn_x + 10 and plr.x + 5 > pu.spawn_x and
                        plr.y < pu.spawn_y + 10 and plr.y + 13 > pu.spawn_y):
                    pu.active = False
                    pu.respawn_timer = POWER_UP_RESPAWN_TIME
                    duration = POWER_UP_DURATIONS[pu.pu_type]
                    # Server-side effects
                    if pu.pu_type == "shield":
                        plr.shield_until = now + duration
                    self.broadcast({
                        "type": "powerup_pickup",
                        "pu_id": pu.pu_id,
                        "pu_type": pu.pu_type,
                        "player_id": plr.player_id,
                        "duration": duration,
                    })
                    print(f"Player {plr.player_id} picked up {pu.pu_type}")
                    break

    def build_world_msg(self) -> dict:
        now = time.time()
        return {
            "type": "world",
            "players": {
                str(pid): {
                    "x": p.x, "y": p.y,
                    "vx": p.vx, "vy": p.vy,
                    "facing": p.facing,
                    "team_id": p.team_id,
                    "team_color": TEAM_COLORS[p.team_id % len(TEAM_COLORS)],
                    "alive": p.alive,
                    "name": p.name,
                    "hp": p.hp,
                    "shield_active": now < p.shield_until,
                }
                for pid, p in self.players.items()
            },
            "projectiles": {
                str(pid): {
                    "x": pr.x, "y": pr.y,
                    "vx": pr.vx, "vy": pr.vy,
                    "team_id": pr.team_id,
                }
                for pid, pr in self.projectiles.items()
            },
            "power_ups": {
                str(pu.pu_id): {
                    "x": pu.spawn_x,
                    "y": pu.spawn_y,
                    "type": pu.pu_type,
                    "active": pu.active,
                    "lifetime": pu.lifetime_timer,
                }
                for pu in self.power_ups.values()
            },
        }

    def check_win_condition(self) -> None:
        truly_alive = set()
        for p in self.players.values():
            if p.alive:
                truly_alive.add(p.team_id)
        if len(truly_alive) <= 1 and self.game_started:
            any_respawning = any(not p.alive and p.respawn_timer > 0 for p in self.players.values())
            if any_respawning:
                return
            if len(truly_alive) == 1:
                winner = truly_alive.pop()
                self.game_over = True
                self.broadcast({
                    "type": "game_over",
                    "winner_team": winner,
                    "team_color": TEAM_COLORS[winner % len(TEAM_COLORS)],
                })
            elif len(truly_alive) == 0:
                self.game_over = True
                self.broadcast({
                    "type": "game_over",
                    "winner_team": -1,
                    "team_color": [200, 200, 200],
                })

    def respawn_player(self, player_id: int) -> None:
        p = self.players[player_id]
        # Spawn at a random valid floor position anywhere on the map
        p.x, p.y = rand_player_pos()
        p.vx = p.vy = 0.0
        p.alive = True
        p.hp = PLAYER_MAX_HP
        p.shield_until = 0.0
        self.broadcast({
            "type": "respawn",
            "player_id": player_id,
            "x": p.x, "y": p.y,
            "hp": p.hp,
        })

    def tick_respawns(self, dt: float) -> None:
        for p in list(self.players.values()):
            if not p.alive and p.respawn_timer > 0:
                p.respawn_timer -= dt
                if p.respawn_timer <= 0:
                    self.respawn_player(p.player_id)

    def process_message(self, player_id: int, msg: dict) -> None:
        mtype = msg.get("type")

        if mtype == "join":
            p = PlayerState(
                player_id=player_id,
                name=msg.get("name", f"Player{player_id}"),
            )
            self.players[player_id] = p
            print(f"Player {player_id} ({p.name}) joined lobby")
            self.send_to(player_id, {
                "type": "welcome",
                "player_id": player_id,
                "num_teams": NUM_TEAMS,
                "max_hp": PLAYER_MAX_HP,
            })
            self.broadcast(self.get_lobby_info())

        elif mtype == "select_team":
            p = self.players.get(player_id)
            if p and not self.game_started:
                team_id = int(msg.get("team_id", 0))
                if 0 <= team_id < NUM_TEAMS:
                    count = sum(1 for pp in self.players.values() if pp.team_id == team_id)
                    max_per_team = max(1, MAX_PLAYERS // NUM_TEAMS)
                    if count < max_per_team or p.team_id == team_id:
                        p.team_id = team_id
                        p.ready = False
                        print(f"Player {player_id} selected team {team_id}")
                self.broadcast(self.get_lobby_info())

        elif mtype == "ready":
            p = self.players.get(player_id)
            if p and not self.game_started and p.team_id >= 0:
                p.ready = bool(msg.get("ready", True))
                print(f"Player {player_id} ready={p.ready}")
                self.broadcast(self.get_lobby_info())
                if self.check_all_ready():
                    self.start_game()

        elif mtype == "state":
            if not self.game_started:
                return
            p = self.players.get(player_id)
            if p and p.alive:
                p.x = float(msg.get("x", p.x))
                p.y = float(msg.get("y", p.y))
                p.vx = float(msg.get("vx", p.vx))
                p.vy = float(msg.get("vy", p.vy))
                p.on_ground = bool(msg.get("on_ground", False))
                p.facing = msg.get("facing", p.facing)

        elif mtype == "throw":
            if not self.game_started:
                return
            p = self.players.get(player_id)
            if p and p.alive:
                facing = msg.get("facing", p.facing)
                self.spawn_projectile(player_id, facing)

    def remove_player(self, player_id: int) -> None:
        self.players.pop(player_id, None)
        self.clients.pop(player_id, None)
        print(f"Player {player_id} disconnected")
        self.broadcast({"type": "player_left", "player_id": player_id})
        if not self.game_started:
            self.broadcast(self.get_lobby_info())

    def handle_client(self, conn: socket.socket, player_id: int) -> None:
        buf = ""
        try:
            while not self.game_over:
                data = conn.recv(4096).decode("utf-8")
                if not data:
                    break
                buf += data
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        with self.lock:
                            self.process_message(player_id, msg)
        except (ConnectionResetError, OSError):
            pass
        finally:
            with self.lock:
                self.remove_player(player_id)
            conn.close()

    def world_broadcast_loop(self) -> None:
        interval = 1.0 / TICK_RATE
        while not self.game_over:
            time.sleep(interval)
            with self.lock:
                if self.game_started and self.players:
                    self.tick_respawns(interval)
                    self.tick_projectiles(interval)
                    self.tick_power_ups(interval)
                    self.broadcast(self.build_world_msg())

    def run(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(MAX_PLAYERS)
        print(f"Server listening on {HOST}:{PORT} (teams={NUM_TEAMS}, max_players={MAX_PLAYERS})")
        print("Waiting for players to join and ready up...")

        threading.Thread(target=self.world_broadcast_loop, daemon=True).start()

        while not self.game_over:
            try:
                conn, addr = srv.accept()
            except OSError:
                break
            with self.lock:
                if len(self.players) >= MAX_PLAYERS:
                    conn.close()
                    continue
                if self.game_started:
                    conn.close()
                    continue
                pid = self.next_id
                self.next_id += 1
                self.clients[pid] = conn
            print(f"Connection from {addr}, assigned id={pid}")
            threading.Thread(
                target=self.handle_client, args=(conn, pid), daemon=True
            ).start()

        print("Game over. Server shutting down.")
        srv.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        NUM_TEAMS = int(sys.argv[1])
    GameServer().run()
