import socket
import threading
import json
import time
from dataclasses import dataclass, field

HOST = "0.0.0.0"
PORT = 5555
MAX_PLAYERS = 6
TEAM_MODE = "teams"   # "teams" or "solo"
TEAM_SIZE = 2         # 2 or 3 players per team
LIVES_PER_TEAM = 3
TICK_RATE = 20
STOMP_MARGIN = 4
RESPAWN_DELAY = 3.0

RESPAWN_POSITIONS = [(100, 50), (300, 50), (200, 30), (150, 80), (250, 80), (350, 50)]
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
    team_id: int
    x: float = 100.0
    y: float = 100.0
    vx: float = 0.0
    vy: float = 0.0
    on_ground: bool = False
    facing: str = "right"
    alive: bool = True
    respawn_timer: float = 0.0


class GameServer:
    def __init__(self):
        self.players: dict[int, PlayerState] = {}
        self.clients: dict[int, socket.socket] = {}
        self.team_lives: dict[int, int] = {}
        self.next_id: int = 0
        self.lock = threading.Lock()
        self.game_over = False

    def assign_team(self, player_id: int) -> int:
        if TEAM_MODE == "solo":
            tid = player_id
            self.team_lives[tid] = LIVES_PER_TEAM
            return tid
        num_teams = max(1, MAX_PLAYERS // TEAM_SIZE)
        tid = player_id % num_teams
        if tid not in self.team_lives:
            self.team_lives[tid] = LIVES_PER_TEAM
        return tid

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
                }
                for pid, p in self.players.items()
            },
            "team_lives": {str(k): v for k, v in self.team_lives.items()},
        }

    def check_stomps(self, updated_id: int) -> None:
        stomper = self.players.get(updated_id)
        if not stomper or not stomper.alive:
            return
        for pid, victim in list(self.players.items()):
            if pid == updated_id:
                continue
            if not victim.alive:
                continue
            if stomper.team_id == victim.team_id:
                continue
            # Bounding boxes: 5x13 pixels
            s_left   = stomper.x
            s_right  = stomper.x + 5
            s_bottom = stomper.y + 13
            v_left   = victim.x
            v_right  = victim.x + 5
            v_top    = victim.y

            h_overlap = s_right > v_left and s_left < v_right
            v_stomp   = (abs(s_bottom - v_top) <= STOMP_MARGIN and stomper.vy > 0)

            if h_overlap and v_stomp:
                self.register_stomp(updated_id, pid)

    def register_stomp(self, stomper_id: int, victim_id: int) -> None:
        victim = self.players[victim_id]
        if not victim.alive:
            return
        victim.alive = False
        victim.respawn_timer = RESPAWN_DELAY

        tid = victim.team_id
        self.team_lives[tid] = max(0, self.team_lives.get(tid, 0) - 1)

        self.broadcast({
            "type": "stomp",
            "stomper_id": stomper_id,
            "victim_id": victim_id,
            "team_lives": {str(k): v for k, v in self.team_lives.items()},
        })
        self.check_win_condition()

    def check_win_condition(self) -> None:
        alive_teams = [tid for tid, lives in self.team_lives.items() if lives > 0]
        if len(alive_teams) <= 1:
            self.game_over = True
            winner = alive_teams[0] if alive_teams else -1
            self.broadcast({
                "type": "game_over",
                "winner_team": winner,
                "team_color": TEAM_COLORS[winner % len(TEAM_COLORS)] if winner >= 0 else [200, 200, 200],
            })

    def respawn_player(self, player_id: int) -> None:
        p = self.players[player_id]
        spawn = RESPAWN_POSITIONS[player_id % len(RESPAWN_POSITIONS)]
        p.x, p.y = float(spawn[0]), float(spawn[1])
        p.vx = p.vy = 0.0
        p.alive = True
        self.send_to(player_id, {
            "type": "respawn",
            "player_id": player_id,
            "x": p.x, "y": p.y,
        })

    def tick_respawns(self, dt: float) -> None:
        for p in list(self.players.values()):
            if not p.alive and p.respawn_timer > 0:
                if self.team_lives.get(p.team_id, 0) > 0:
                    p.respawn_timer -= dt
                    if p.respawn_timer <= 0:
                        self.respawn_player(p.player_id)

    def process_message(self, player_id: int, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "join":
            tid = self.assign_team(player_id)
            spawn = RESPAWN_POSITIONS[player_id % len(RESPAWN_POSITIONS)]
            p = PlayerState(
                player_id=player_id,
                name=msg.get("name", f"Player{player_id}"),
                team_id=tid,
                x=float(spawn[0]),
                y=float(spawn[1]),
            )
            self.players[player_id] = p
            print(f"Player {player_id} ({p.name}) joined team {tid}")
            self.send_to(player_id, {
                "type": "welcome",
                "player_id": player_id,
                "team_id": tid,
                "team_color": TEAM_COLORS[tid % len(TEAM_COLORS)],
                "lives": self.team_lives.get(tid, LIVES_PER_TEAM),
                "mode": TEAM_MODE,
                "spawn_x": spawn[0], "spawn_y": spawn[1],
            })
            # Notify others
            self.broadcast({
                "type": "player_joined",
                "player_id": player_id,
                "name": p.name,
                "team_id": tid,
                "team_color": TEAM_COLORS[tid % len(TEAM_COLORS)],
            })

        elif mtype == "state":
            p = self.players.get(player_id)
            if p and p.alive:
                p.x = float(msg.get("x", p.x))
                p.y = float(msg.get("y", p.y))
                p.vx = float(msg.get("vx", p.vx))
                p.vy = float(msg.get("vy", p.vy))
                p.on_ground = bool(msg.get("on_ground", False))
                p.facing = msg.get("facing", p.facing)
                self.check_stomps(player_id)

    def remove_player(self, player_id: int) -> None:
        self.players.pop(player_id, None)
        self.clients.pop(player_id, None)
        print(f"Player {player_id} disconnected")
        self.broadcast({"type": "player_left", "player_id": player_id})

    def handle_client(self, conn: socket.socket, player_id: int) -> None:
        buf = ""
        try:
            while not self.game_over:
                data = conn.recv(1024).decode("utf-8")
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
                self.tick_respawns(interval)
                if self.players:
                    self.broadcast(self.build_world_msg())

    def run(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(MAX_PLAYERS)
        print(f"Server listening on {HOST}:{PORT}  (mode={TEAM_MODE}, team_size={TEAM_SIZE})")
        print(f"Waiting for {MIN_TO_START}-{MAX_PLAYERS} players...")

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
                pid = self.next_id
                self.next_id += 1
                self.clients[pid] = conn
            print(f"Connection from {addr}, assigned id={pid}")
            threading.Thread(
                target=self.handle_client, args=(conn, pid), daemon=True
            ).start()

        print("Game over. Server shutting down.")
        srv.close()


MIN_TO_START = 2

if __name__ == "__main__":
    import sys
    # Allow: python server.py [solo|teams] [team_size]
    if len(sys.argv) >= 2:
        TEAM_MODE = sys.argv[1]
    if len(sys.argv) >= 3:
        TEAM_SIZE = int(sys.argv[2])
    GameServer().run()
