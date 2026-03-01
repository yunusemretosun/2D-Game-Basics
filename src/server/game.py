"""GameServer: handles all networking, game logic, and ticking."""
import json
import random
import socket
import threading
import time

from src.constants import (
    HOST, PORT, MAX_PLAYERS, NUM_TEAMS, TICK_RATE,
    PLAYER_MAX_HP, RESPAWN_DELAY,
    TEAM_COLORS, TEAM_SPAWN_AREAS,
    SHOP_X, SHOP_Y, SHOP_RADIUS,
    KILL_COIN_REWARD, STARTING_COINS,
    WEAPONS, POWER_UP_TYPES, POWER_UP_DURATIONS, NUM_POWER_UPS,
    POWER_UP_RESPAWN_TIME, POWER_UP_LIFETIME,
)
from src.server.entities import (
    PlayerState, Projectile, PowerUp, DroppedWeapon,
    rand_player_pos, rand_powerup_pos,
)


class GameServer:
    def __init__(self):
        self.players:         dict[int, PlayerState]   = {}
        self.clients:         dict[int, socket.socket] = {}
        self.projectiles:     dict[int, Projectile]    = {}
        self.power_ups:       dict[int, PowerUp]       = {}
        self.dropped_weapons: dict[int, DroppedWeapon] = {}
        self.next_id       = 0
        self.next_proj_id  = 0
        self.next_drop_id  = 0
        self.lock          = threading.Lock()
        self.game_over     = False
        self.game_started  = False

    # ── Networking ────────────────────────────────────────────────────────────

    def send_to(self, player_id: int, msg: dict) -> None:
        conn = self.clients.get(player_id)
        if conn:
            try:
                conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
            except Exception:
                pass

    def broadcast(self, msg: dict) -> None:
        data = (json.dumps(msg) + "\n").encode("utf-8")
        for conn in list(self.clients.values()):
            try:
                conn.sendall(data)
            except Exception:
                pass

    # ── Lobby ─────────────────────────────────────────────────────────────────

    def _get_lobby_info(self) -> dict:
        counts = {}
        for p in self.players.values():
            if p.team_id >= 0:
                counts[p.team_id] = counts.get(p.team_id, 0) + 1
        players_info = {
            str(pid): {"name": p.name, "team_id": p.team_id, "ready": p.ready}
            for pid, p in self.players.items()
        }
        return {
            "type": "lobby_update",
            "players": players_info,
            "team_counts": {str(k): v for k, v in counts.items()},
            "game_started": self.game_started,
        }

    def _check_all_ready(self) -> bool:
        if len(self.players) < 2:
            return False
        return all(p.team_id >= 0 and p.ready for p in self.players.values())

    def start_game(self) -> None:
        self.game_started = True

        # Assign initial spawn positions
        for p in self.players.values():
            spawns = TEAM_SPAWN_AREAS.get(p.team_id, TEAM_SPAWN_AREAS[0])
            team_members = [pp for pp in self.players.values() if pp.team_id == p.team_id]
            idx = team_members.index(p) % len(spawns)
            p.x, p.y       = float(spawns[idx][0]), float(spawns[idx][1])
            p.hp            = PLAYER_MAX_HP
            p.alive         = True
            p.shield_until  = 0.0
            p.weapon        = "pistol"
            p.coins         = STARTING_COINS
            p.reload_until  = 0.0

        # Spawn power-ups at random valid positions
        shuffled = POWER_UP_TYPES.copy()
        random.shuffle(shuffled)
        for i in range(NUM_POWER_UPS):
            pu_type = shuffled[i % len(shuffled)]
            px, py  = rand_powerup_pos()
            self.power_ups[i] = PowerUp(pu_id=i, pu_type=pu_type, spawn_x=px, spawn_y=py)

        # Notify each player of their spawn and share weapon/shop data
        for p in self.players.values():
            self.send_to(p.player_id, {
                "type":    "game_start",
                "spawn_x": p.x, "spawn_y": p.y,
                "shop_x":  SHOP_X, "shop_y": SHOP_Y,
                "weapons": WEAPONS,
            })
        print("Game started!")

    # ── Weapon helpers ────────────────────────────────────────────────────────

    def spawn_projectile(self, owner_id: int, facing: str) -> None:
        p = self.players.get(owner_id)
        if not p or not p.alive:
            return
        now = time.time()
        if now < p.reload_until:
            return

        weapon   = WEAPONS.get(p.weapon, WEAPONS["pistol"])
        speed    = weapon["bullet_speed"]
        lifetime = weapon["range_px"] / (speed * 60)
        damage   = weapon["damage"]
        p.reload_until = now + weapon["reload_time"]

        for i in range(weapon["pellets"]):
            pid = self.next_proj_id
            self.next_proj_id += 1
            vx = speed if facing == "right" else -speed
            if weapon["pellets"] > 1:
                vy = -(weapon["pellets"] - 1) / 2.0 * weapon["spread"] + i * weapon["spread"]
            else:
                vy = 0.0

            proj = Projectile(
                proj_id=pid, owner_id=owner_id, team_id=p.team_id,
                x=p.x + (5 if facing == "right" else -4),
                y=p.y + 5,
                vx=vx, vy=vy,
                lifetime=lifetime, damage=damage, weapon_id=p.weapon,
            )
            self.projectiles[pid] = proj
            self.broadcast({
                "type": "projectile_spawn",
                "proj_id": pid, "owner_id": owner_id, "team_id": p.team_id,
                "x": proj.x, "y": proj.y, "vx": proj.vx, "vy": proj.vy,
                "weapon_id": p.weapon,
            })

    def _drop_weapon(self, player: PlayerState) -> None:
        """Drop player's current weapon (except pistol) at their position."""
        if player.weapon == "pistol":
            return
        drop_id  = self.next_drop_id
        self.next_drop_id += 1
        drop = DroppedWeapon(drop_id=drop_id, weapon_id=player.weapon,
                             x=player.x, y=player.y)
        self.dropped_weapons[drop_id] = drop
        player.weapon = "pistol"
        self.broadcast({
            "type": "weapon_dropped",
            "drop_id": drop_id, "weapon_id": drop.weapon_id,
            "x": drop.x, "y": drop.y,
        })

    # ── Tick functions ────────────────────────────────────────────────────────

    def tick_projectiles(self, dt: float) -> None:
        now = time.time()
        to_remove = []
        for pid, proj in list(self.projectiles.items()):
            proj.x        += proj.vx * dt * 60
            proj.y        += proj.vy * dt * 60
            proj.lifetime -= dt
            if proj.lifetime <= 0 or proj.x < -50 or proj.x > 1100 or proj.y > 500:
                to_remove.append(pid)
                continue
            for plr in list(self.players.values()):
                if plr.player_id == proj.owner_id or plr.team_id == proj.team_id:
                    continue
                if not plr.alive or now < plr.shield_until:
                    continue
                if (proj.x + 4 > plr.x and proj.x < plr.x + 5 and
                        proj.y + 4 > plr.y and proj.y < plr.y + 13):
                    plr.hp -= proj.damage
                    self.broadcast({
                        "type": "projectile_hit", "proj_id": pid,
                        "victim_id": plr.player_id, "damage": proj.damage, "hp": plr.hp,
                    })
                    to_remove.append(pid)
                    if plr.hp <= 0:
                        plr.alive = False
                        plr.hp    = 0
                        plr.respawn_timer = RESPAWN_DELAY
                        self._drop_weapon(plr)
                        killer = self.players.get(proj.owner_id)
                        if killer:
                            killer.coins += KILL_COIN_REWARD
                            self.send_to(proj.owner_id, {"type": "coins_update", "coins": killer.coins})
                        self.broadcast({"type": "player_killed",
                                        "victim_id": plr.player_id, "killer_id": proj.owner_id})
                        self.check_win_condition()
                    break
        for pid in to_remove:
            self.projectiles.pop(pid, None)

    def tick_dropped_weapons(self, dt: float) -> None:
        to_remove = []
        for drop_id, drop in list(self.dropped_weapons.items()):
            drop.lifetime -= dt
            if drop.lifetime <= 0:
                to_remove.append(drop_id)
                self.broadcast({"type": "weapon_gone", "drop_id": drop_id})
                continue
            for plr in list(self.players.values()):
                if not plr.alive:
                    continue
                if (plr.x < drop.x + 10 and plr.x + 5 > drop.x and
                        plr.y < drop.y + 10 and plr.y + 13 > drop.y):
                    to_remove.append(drop_id)
                    plr.weapon = drop.weapon_id
                    self.broadcast({"type": "weapon_pickup",
                                    "drop_id": drop_id, "player_id": plr.player_id,
                                    "weapon_id": drop.weapon_id})
                    break
        for drop_id in to_remove:
            self.dropped_weapons.pop(drop_id, None)

    def tick_power_ups(self, dt: float) -> None:
        now = time.time()
        for pu in list(self.power_ups.values()):
            if not pu.active:
                pu.respawn_timer -= dt
                if pu.respawn_timer <= 0:
                    pu.spawn_x, pu.spawn_y = rand_powerup_pos()
                    pu.active         = True
                    pu.lifetime_timer = POWER_UP_LIFETIME
                    idx = POWER_UP_TYPES.index(pu.pu_type)
                    pu.pu_type = POWER_UP_TYPES[(idx + 1) % len(POWER_UP_TYPES)]
                continue

            pu.lifetime_timer -= dt
            if pu.lifetime_timer <= 0:
                pu.active        = False
                pu.respawn_timer = POWER_UP_RESPAWN_TIME
                self.broadcast({"type": "powerup_expired", "pu_id": pu.pu_id})
                continue

            for plr in list(self.players.values()):
                if not plr.alive:
                    continue
                if (plr.x < pu.spawn_x + 10 and plr.x + 5 > pu.spawn_x and
                        plr.y < pu.spawn_y + 10 and plr.y + 13 > pu.spawn_y):
                    pu.active        = False
                    pu.respawn_timer = POWER_UP_RESPAWN_TIME
                    duration = POWER_UP_DURATIONS[pu.pu_type]
                    if pu.pu_type == "shield":
                        plr.shield_until = now + duration
                    self.broadcast({
                        "type": "powerup_pickup", "pu_id": pu.pu_id,
                        "pu_type": pu.pu_type, "player_id": plr.player_id,
                        "duration": duration,
                    })
                    print(f"Player {plr.player_id} picked up {pu.pu_type}")
                    break

    def tick_respawns(self, dt: float) -> None:
        for p in list(self.players.values()):
            if not p.alive and p.respawn_timer > 0:
                p.respawn_timer -= dt
                if p.respawn_timer <= 0:
                    self._respawn_player(p.player_id)

    # ── World state ───────────────────────────────────────────────────────────

    def build_world_msg(self) -> dict:
        now = time.time()
        return {
            "type": "world",
            "players": {
                str(pid): {
                    "x": p.x, "y": p.y, "vx": p.vx, "vy": p.vy,
                    "facing": p.facing, "team_id": p.team_id,
                    "team_color": TEAM_COLORS[p.team_id % len(TEAM_COLORS)],
                    "alive": p.alive, "name": p.name, "hp": p.hp,
                    "shield_active": now < p.shield_until,
                    "weapon": p.weapon, "coins": p.coins,
                    "reload_left": max(0.0, p.reload_until - now),
                }
                for pid, p in self.players.items()
            },
            "projectiles": {
                str(pid): {
                    "x": pr.x, "y": pr.y, "vx": pr.vx, "vy": pr.vy,
                    "team_id": pr.team_id, "weapon_id": pr.weapon_id,
                }
                for pid, pr in self.projectiles.items()
            },
            "power_ups": {
                str(pu.pu_id): {
                    "x": pu.spawn_x, "y": pu.spawn_y,
                    "type": pu.pu_type, "active": pu.active, "lifetime": pu.lifetime_timer,
                }
                for pu in self.power_ups.values()
            },
            "dropped_weapons": {
                str(drop_id): {
                    "weapon_id": drop.weapon_id,
                    "x": drop.x, "y": drop.y, "lifetime": drop.lifetime,
                }
                for drop_id, drop in self.dropped_weapons.items()
            },
        }

    def check_win_condition(self) -> None:
        alive_teams = {p.team_id for p in self.players.values() if p.alive}
        if len(alive_teams) <= 1 and self.game_started:
            respawning = any(not p.alive and p.respawn_timer > 0 for p in self.players.values())
            if respawning:
                return
            if len(alive_teams) == 1:
                winner = alive_teams.pop()
                self.game_over = True
                self.broadcast({"type": "game_over", "winner_team": winner,
                                "team_color": TEAM_COLORS[winner % len(TEAM_COLORS)]})
            else:
                self.game_over = True
                self.broadcast({"type": "game_over", "winner_team": -1,
                                "team_color": [200, 200, 200]})

    def _respawn_player(self, player_id: int) -> None:
        p      = self.players[player_id]
        p.x, p.y      = rand_player_pos()
        p.vx = p.vy   = 0.0
        p.alive        = True
        p.hp           = PLAYER_MAX_HP
        p.shield_until = 0.0
        self.broadcast({
            "type": "respawn", "player_id": player_id,
            "x": p.x, "y": p.y, "hp": p.hp,
            "weapon": p.weapon, "coins": p.coins,
        })

    # ── Message dispatch ──────────────────────────────────────────────────────

    def process_message(self, player_id: int, msg: dict) -> None:
        mtype = msg.get("type")

        if mtype == "join":
            p = PlayerState(player_id=player_id, name=msg.get("name", f"Player{player_id}"))
            self.players[player_id] = p
            print(f"Player {player_id} ({p.name}) joined lobby")
            self.send_to(player_id, {
                "type": "welcome", "player_id": player_id,
                "num_teams": NUM_TEAMS, "max_hp": PLAYER_MAX_HP,
            })
            self.broadcast(self._get_lobby_info())

        elif mtype == "select_team":
            p = self.players.get(player_id)
            if p and not self.game_started:
                team_id = int(msg.get("team_id", 0))
                if 0 <= team_id < NUM_TEAMS:
                    count = sum(1 for pp in self.players.values() if pp.team_id == team_id)
                    max_per = max(1, MAX_PLAYERS // NUM_TEAMS)
                    if count < max_per or p.team_id == team_id:
                        p.team_id = team_id
                        p.ready   = False
                self.broadcast(self._get_lobby_info())

        elif mtype == "ready":
            p = self.players.get(player_id)
            if p and not self.game_started and p.team_id >= 0:
                p.ready = bool(msg.get("ready", True))
                self.broadcast(self._get_lobby_info())
                if self._check_all_ready():
                    self.start_game()

        elif mtype == "state":
            if not self.game_started:
                return
            p = self.players.get(player_id)
            if p and p.alive:
                p.x        = float(msg.get("x",        p.x))
                p.y        = float(msg.get("y",        p.y))
                p.vx       = float(msg.get("vx",       p.vx))
                p.vy       = float(msg.get("vy",       p.vy))
                p.on_ground = bool(msg.get("on_ground", False))
                p.facing   = msg.get("facing", p.facing)

        elif mtype == "throw":
            if not self.game_started:
                return
            p = self.players.get(player_id)
            if p and p.alive:
                self.spawn_projectile(player_id, msg.get("facing", p.facing))

        elif mtype == "buy_weapon":
            if not self.game_started:
                return
            p = self.players.get(player_id)
            if not p or not p.alive:
                return
            weapon_id = msg.get("weapon_id")
            if weapon_id not in WEAPONS:
                return
            weapon = WEAPONS[weapon_id]
            dx = p.x - SHOP_X
            dy = p.y - (SHOP_Y - 13)
            if dx * dx + dy * dy > SHOP_RADIUS ** 2:
                self.send_to(player_id, {"type": "buy_failed", "reason": "too_far"})
                return
            if p.coins < weapon["price"]:
                self.send_to(player_id, {"type": "buy_failed", "reason": "insufficient_coins"})
                return
            p.coins  -= weapon["price"]
            p.weapon  = weapon_id
            self.send_to(player_id, {"type": "weapon_bought", "weapon_id": weapon_id, "coins": p.coins})
            print(f"Player {player_id} bought {weapon_id} ({p.coins} coins left)")

    def remove_player(self, player_id: int) -> None:
        self.players.pop(player_id, None)
        self.clients.pop(player_id, None)
        print(f"Player {player_id} disconnected")
        self.broadcast({"type": "player_left", "player_id": player_id})
        if not self.game_started:
            self.broadcast(self._get_lobby_info())

    # ── Client thread ─────────────────────────────────────────────────────────

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
                    if not line:
                        continue
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

    # ── Broadcast loop ────────────────────────────────────────────────────────

    def world_broadcast_loop(self) -> None:
        interval = 1.0 / TICK_RATE
        while not self.game_over:
            import time as _t
            _t.sleep(interval)
            with self.lock:
                if self.game_started and self.players:
                    self.tick_respawns(interval)
                    self.tick_projectiles(interval)
                    self.tick_power_ups(interval)
                    self.tick_dropped_weapons(interval)
                    self.broadcast(self.build_world_msg())

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, num_teams: int = NUM_TEAMS) -> None:
        import sys
        # Allow overriding NUM_TEAMS via arg
        global NUM_TEAMS  # noqa: PLW0603
        NUM_TEAMS = num_teams

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(MAX_PLAYERS)
        print(f"Server listening on {HOST}:{PORT}  (teams={num_teams}, max_players={MAX_PLAYERS})")
        print("Waiting for players to join and ready up...")

        threading.Thread(target=self.world_broadcast_loop, daemon=True).start()

        while not self.game_over:
            try:
                conn, addr = srv.accept()
            except OSError:
                break
            with self.lock:
                if len(self.players) >= MAX_PLAYERS or self.game_started:
                    conn.close()
                    continue
                pid = self.next_id
                self.next_id += 1
                self.clients[pid] = conn
            print(f"Connection from {addr}, assigned id={pid}")
            threading.Thread(target=self.handle_client, args=(conn, pid), daemon=True).start()

        print("Game over. Server shutting down.")
        srv.close()
