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

# Fixed spawn positions on the map (on top of platforms/floor tiles)
POWER_UP_SPAWN_LOCATIONS = [
    (112, 316),   # left area, main floor
    (288, 316),   # left-center, main floor
    (480, 224),   # on center mid-platform (row 16)
    (672, 316),   # right-center, main floor
    (848, 316),   # right area, main floor
    (320, 156),   # on a mid-height platform
    (640, 156),   # on a mid-height platform (other side)
]

POWER_UP_RESPAWN_TIME = 15.0  # seconds until power-up reappears


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

        # Initialize power-ups at fixed locations, cycling through types
        shuffled_types = POWER_UP_TYPES.copy()
        random.shuffle(shuffled_types)
        for i, (sx, sy) in enumerate(POWER_UP_SPAWN_LOCATIONS):
            pu_type = shuffled_types[i % len(shuffled_types)]
            pu = PowerUp(pu_id=i, pu_type=pu_type, spawn_x=float(sx), spawn_y=float(sy))
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
                    pu.active = True
                    # Cycle to next type
                    idx = POWER_UP_TYPES.index(pu.pu_type)
                    pu.pu_type = POWER_UP_TYPES[(idx + 1) % len(POWER_UP_TYPES)]
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
        spawns = TEAM_SPAWN_AREAS.get(p.team_id, TEAM_SPAWN_AREAS[0])
        team_members = [pp for pp in self.players.values() if pp.team_id == p.team_id]
        idx = 0
        for i, pp in enumerate(team_members):
            if pp.player_id == player_id:
                idx = i % len(spawns)
                break
        sx, sy = spawns[idx]
        p.x, p.y = float(sx), float(sy)
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
