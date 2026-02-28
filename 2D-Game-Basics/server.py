import socket
import threading
import json
import time
import math
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
PROJECTILE_LIFETIME = 3.0  # seconds

# Team spawn areas: (x, y) — each team spawns together on one side
TEAM_SPAWN_AREAS = {
    0: [(50, 200), (70, 200), (90, 200)],     # left side
    1: [(460, 200), (480, 200), (500, 200)],   # right side
    2: [(250, 100), (270, 100), (290, 100)],   # center top
}

TEAM_COLORS = [
    [220, 60,  60],
    [60,  100, 220],
    [60,  200, 60],
    [220, 180, 50],
    [180, 60,  220],
    [60,  200, 200],
]


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


class GameServer:
    def __init__(self):
        self.players: dict[int, PlayerState] = {}
        self.clients: dict[int, socket.socket] = {}
        self.projectiles: dict[int, Projectile] = {}
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
        # Assign spawn positions per team
        for p in self.players.values():
            spawns = TEAM_SPAWN_AREAS.get(p.team_id, TEAM_SPAWN_AREAS[0])
            # Count how many players in this team already spawned before this one
            team_members = [pp for pp in self.players.values()
                           if pp.team_id == p.team_id]
            idx = team_members.index(p) % len(spawns)
            sx, sy = spawns[idx]
            p.x, p.y = float(sx), float(sy)
            p.hp = PLAYER_MAX_HP
            p.alive = True

        # Send game_start to everyone with their spawn position
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
        to_remove = []
        for pid, proj in list(self.projectiles.items()):
            proj.x += proj.vx * dt * 60
            proj.y += proj.vy * dt * 60
            proj.lifetime -= dt
            if proj.lifetime <= 0 or proj.x < -50 or proj.x > 1100 or proj.y > 500:
                to_remove.append(pid)
                continue
            # Check collision with players
            proj_rect_x = proj.x
            proj_rect_y = proj.y
            for plr in list(self.players.values()):
                if plr.player_id == proj.owner_id:
                    continue
                if plr.team_id == proj.team_id:
                    continue
                if not plr.alive:
                    continue
                # Simple AABB: projectile is 4x4, player is 5x13
                if (proj_rect_x + 4 > plr.x and proj_rect_x < plr.x + 5 and
                        proj_rect_y + 4 > plr.y and proj_rect_y < plr.y + 13):
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

    def build_world_msg(self) -> dict:
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
        }

    def check_win_condition(self) -> None:
        alive_teams = set()
        for p in self.players.values():
            if p.alive or p.respawn_timer > 0:
                alive_teams.add(p.team_id)
        # Also count teams that have alive members
        truly_alive = set()
        for p in self.players.values():
            if p.alive:
                truly_alive.add(p.team_id)
        if len(truly_alive) <= 1 and self.game_started:
            # Check if any dead players are still respawning
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
                    # Check team capacity
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
