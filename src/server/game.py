"""GameServer: networking, game logic, ticking."""
import json
import math
import random
import socket
import threading
import time

from src.constants import (
    HOST, PORT, MAX_PLAYERS, NUM_TEAMS, TICK_RATE,
    PLAYER_MAX_HP, PLAYER_W, PLAYER_H, RESPAWN_DELAY, RESPAWN_SHIELD,
    TEAM_COLORS, TEAM_SPAWN_AREAS, KILL_LIMIT,
    SHOP_X, SHOP_Y, SHOP_RADIUS,
    KILL_COIN_REWARD, STARTING_COINS,
    WEAPONS, POWER_UP_TYPES, POWER_UP_DURATIONS, NUM_POWER_UPS,
    POWER_UP_RESPAWN_TIME, POWER_UP_LIFETIME,
    BREAKABLE_DEFS, BREAKABLE_HP, BREAKABLE_COIN_RANGE,
    BREAKABLE_PROJECTILE_DAMAGE,
)
from src.server.entities import (
    PlayerState, Projectile, PowerUp, DroppedWeapon, BreakableObject,
    rand_player_pos, rand_powerup_pos,
)


class GameServer:
    def __init__(self):
        self.players:          dict[int, PlayerState]    = {}
        self.clients:          dict[int, socket.socket]  = {}
        self.projectiles:      dict[int, Projectile]     = {}
        self.power_ups:        dict[int, PowerUp]        = {}
        self.dropped_weapons:  dict[int, DroppedWeapon]  = {}
        self.objects:          dict[int, BreakableObject] = {}
        self.next_id      = 0
        self.next_proj_id = 0
        self.next_drop_id = 0
        self.lock         = threading.Lock()
        self.game_over    = False
        self.game_started = False
        # team kill counts for score-based win
        self.team_kills: dict[int, int] = {}

    # ── Networking ────────────────────────────────────────────────────────────

    def send_to(self, pid: int, msg: dict) -> None:
        conn = self.clients.get(pid)
        if conn:
            try:
                conn.sendall((json.dumps(msg) + "\n").encode())
            except Exception:
                pass

    def broadcast(self, msg: dict) -> None:
        data = (json.dumps(msg) + "\n").encode()
        for conn in list(self.clients.values()):
            try:
                conn.sendall(data)
            except Exception:
                pass

    # ── Lobby ─────────────────────────────────────────────────────────────────

    def _get_lobby_info(self) -> dict:
        return {
            "type": "lobby_update",
            "players": {
                str(pid): {"name": p.name, "team_id": p.team_id, "ready": p.ready}
                for pid, p in self.players.items()
            },
            "game_started": self.game_started,
        }

    def _check_all_ready(self) -> bool:
        if len(self.players) < 2:
            return False
        return all(p.team_id >= 0 and p.ready for p in self.players.values())

    def start_game(self) -> None:
        self.game_started = True
        now = time.time()

        # Initialise team kills
        teams = {p.team_id for p in self.players.values() if p.team_id >= 0}
        self.team_kills = {t: 0 for t in teams}

        # Initial spawn positions
        for p in self.players.values():
            spawns = TEAM_SPAWN_AREAS.get(p.team_id, [(100, 100)])
            members = [pp for pp in self.players.values() if pp.team_id == p.team_id]
            idx = members.index(p) % len(spawns)
            p.x, p.y     = float(spawns[idx][0]), float(spawns[idx][1])
            p.hp          = PLAYER_MAX_HP
            p.alive       = True
            p.shield_until = now + RESPAWN_SHIELD   # start with brief shield
            p.weapon      = "pistol"
            p.coins       = STARTING_COINS
            p.reload_until = 0.0
            p.kills       = 0

        # Power-ups – stagger lifetime_timer so they don't all expire together
        shuffled = POWER_UP_TYPES.copy()
        random.shuffle(shuffled)
        for i in range(NUM_POWER_UPS):
            pu_type = shuffled[i % len(shuffled)]
            px, py  = rand_powerup_pos()
            # stagger: each PU starts with a different fraction of lifetime
            stagger = POWER_UP_LIFETIME * (i / NUM_POWER_UPS)
            self.power_ups[i] = PowerUp(
                pu_id=i, pu_type=pu_type, spawn_x=px, spawn_y=py,
                lifetime_timer=stagger + random.uniform(0, 3.0),
            )

        # Breakable objects
        for i, (obj_type, wx, wy) in enumerate(BREAKABLE_DEFS):
            hp = BREAKABLE_HP[obj_type]
            self.objects[i] = BreakableObject(
                obj_id=i, obj_type=obj_type, x=float(wx), y=float(wy),
                hp=hp, max_hp=hp,
            )

        for p in self.players.values():
            self.send_to(p.player_id, {
                "type":    "game_start",
                "spawn_x": p.x, "spawn_y": p.y,
                "shop_x":  SHOP_X, "shop_y": SHOP_Y,
                "weapons": WEAPONS,
                "kill_limit": KILL_LIMIT,
                "objects": {
                    str(o.obj_id): {
                        "type": o.obj_type, "x": o.x, "y": o.y,
                        "hp": o.hp, "max_hp": o.max_hp,
                    }
                    for o in self.objects.values()
                },
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

        weapon      = WEAPONS.get(p.weapon, WEAPONS["pistol"])
        speed       = weapon["bullet_speed"]
        range_px    = float(weapon["range_px"])
        lifetime    = range_px / (speed * 60) * 1.5 + 0.5
        damage      = weapon["damage"]
        # Apply rapid-fire: server checks its own rapid_fire_until, not the client's
        rf_mult     = 0.33 if now < p.rapid_fire_until else 1.0
        p.reload_until = now + weapon["reload_time"] * rf_mult

        for i in range(weapon["pellets"]):
            pid = self.next_proj_id
            self.next_proj_id += 1
            vx = speed if facing == "right" else -speed
            vy = (-(weapon["pellets"] - 1) / 2.0 + i) * weapon["spread"] if weapon["pellets"] > 1 else 0.0

            proj = Projectile(
                proj_id=pid, owner_id=owner_id, team_id=p.team_id,
                x=p.x + (PLAYER_W if facing == "right" else -4),
                y=p.y + PLAYER_H // 2,
                vx=vx, vy=vy,
                lifetime=lifetime, damage=damage, weapon_id=p.weapon,
                range_px=range_px, dist=0.0,
            )
            self.projectiles[pid] = proj

    def _drop_weapon(self, player: PlayerState) -> None:
        """Drop non-pistol weapon on death with a pickup delay."""
        if player.weapon == "pistol":
            return
        drop_id = self.next_drop_id
        self.next_drop_id += 1
        drop = DroppedWeapon(
            drop_id=drop_id, weapon_id=player.weapon,
            x=player.x, y=player.y,
        )
        self.dropped_weapons[drop_id] = drop
        player.weapon = "pistol"
        self.broadcast({
            "type": "weapon_dropped",
            "drop_id": drop_id, "weapon_id": drop.weapon_id,
            "x": drop.x, "y": drop.y,
        })

    # ── Tick functions ────────────────────────────────────────────────────────

    def tick_projectiles(self, dt: float) -> None:
        """Move projectiles in 2-px sub-steps to prevent tunneling.

        Each projectile is advanced in small increments (≤ 2 px) and checked
        for hits at every sub-step, so even the fastest bullet (sniper 42 px/tick)
        cannot pass through the narrowest target (player 8 px wide).

        Bullets are removed when:
          • proj.dist >= proj.range_px  →  range exhausted (visual bullet fade)
          • hit player or object        →  normal removal
          • safety lifetime timeout     →  fallback
        """
        _STEP = 2.0          # max pixels advanced per sub-step
        now   = time.time()
        to_remove: list[int] = []

        for pid, proj in list(self.projectiles.items()):
            # Safety timeout (prevents zombified projectiles)
            proj.lifetime -= dt
            if proj.lifetime <= 0:
                to_remove.append(pid)
                continue

            # Total displacement this tick
            mx = proj.vx * dt * 60
            my = proj.vy * dt * 60
            tick_dist = math.hypot(mx, my)
            if tick_dist == 0:
                to_remove.append(pid)
                continue

            n_steps  = max(1, int(math.ceil(tick_dist / _STEP)))
            sx       = mx / n_steps
            sy       = my / n_steps
            sub_len  = tick_dist / n_steps

            hit            = False
            range_expired  = False

            for _ in range(n_steps):
                proj.x    += sx
                proj.y    += sy
                proj.dist += sub_len

                # ── Range check: bullet has traveled its full range ────────
                if proj.dist >= proj.range_px:
                    range_expired = True
                    break

                # ── World-bounds safety (far outside map) ─────────────────
                if proj.x < -100 or proj.x > 1150 or proj.y < -200 or proj.y > 650:
                    range_expired = True
                    break

                # ── Player hits ───────────────────────────────────────────
                for plr in list(self.players.values()):
                    if plr.player_id == proj.owner_id or plr.team_id == proj.team_id:
                        continue
                    if not plr.alive or now < plr.shield_until:
                        continue
                    if (proj.x + 4 > plr.x and proj.x < plr.x + PLAYER_W and
                            proj.y + 4 > plr.y and proj.y < plr.y + PLAYER_H):
                        plr.hp -= proj.damage
                        self.broadcast({
                            "type":      "projectile_hit",
                            "proj_id":   pid, "victim_id": plr.player_id,
                            "damage":    proj.damage, "hp": max(0, plr.hp),
                            "x": proj.x, "y": proj.y,
                        })
                        to_remove.append(pid)
                        hit = True

                        if plr.hp <= 0:
                            plr.alive         = False
                            plr.hp            = 0
                            plr.respawn_timer = RESPAWN_DELAY
                            self._drop_weapon(plr)

                            killer = self.players.get(proj.owner_id)
                            if killer:
                                killer.coins += KILL_COIN_REWARD
                                killer.kills += 1
                                self.team_kills[killer.team_id] = \
                                    self.team_kills.get(killer.team_id, 0) + 1
                                self.send_to(proj.owner_id, {
                                    "type": "coins_update", "coins": killer.coins
                                })

                            self.broadcast({
                                "type":      "player_killed",
                                "victim_id": plr.player_id,
                                "killer_id": proj.owner_id,
                                "x": plr.x, "y": plr.y,
                            })
                            self.check_win_condition()
                        break

                if hit:
                    break

                # ── Breakable-object hits ─────────────────────────────────
                for obj in list(self.objects.values()):
                    if not obj.alive:
                        continue
                    ox, oy = obj.x, obj.y
                    ow, oh = 16, 32   # covers tree/barrel/crate hitboxes
                    if (proj.x + 4 > ox and proj.x < ox + ow and
                            proj.y + 4 > oy - oh and proj.y < oy + 4):
                        obj.hp -= BREAKABLE_PROJECTILE_DAMAGE
                        self.broadcast({
                            "type":   "object_hit",
                            "obj_id": obj.obj_id, "hp": max(0, obj.hp),
                            "x": proj.x, "y": proj.y,
                        })
                        to_remove.append(pid)
                        if obj.hp <= 0:
                            obj.alive = False
                            lo, hi    = BREAKABLE_COIN_RANGE[obj.obj_type]
                            coins     = random.randint(lo, hi)
                            self.broadcast({
                                "type":   "object_destroyed",
                                "obj_id": obj.obj_id,
                                "x": obj.x, "y": obj.y,
                                "coins":  coins,
                            })
                            shooter = self.players.get(proj.owner_id)
                            if shooter:
                                shooter.coins += coins
                                self.send_to(proj.owner_id, {
                                    "type": "coins_update", "coins": shooter.coins
                                })
                        hit = True
                        break

                if hit:
                    break

            if range_expired:
                to_remove.append(pid)

        for pid in set(to_remove):
            self.projectiles.pop(pid, None)

    def tick_dropped_weapons(self, dt: float) -> None:
        """Advance lifetime timers; pickup is now E-key driven (pick_weapon msg)."""
        to_remove = []
        for drop_id, drop in list(self.dropped_weapons.items()):
            drop.lifetime     -= dt
            drop.pickup_delay -= dt
            if drop.lifetime <= 0:
                to_remove.append(drop_id)
                self.broadcast({"type": "weapon_gone", "drop_id": drop_id})

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
                    # Stagger the new lifetime too
                    pu.lifetime_timer = random.uniform(
                        POWER_UP_LIFETIME * 0.4, POWER_UP_LIFETIME
                    )
                    idx = POWER_UP_TYPES.index(pu.pu_type)
                    pu.pu_type = POWER_UP_TYPES[(idx + 1) % len(POWER_UP_TYPES)]
                continue

            pu.lifetime_timer -= dt
            if pu.lifetime_timer <= 0:
                pu.active        = False
                pu.respawn_timer = random.uniform(
                    POWER_UP_RESPAWN_TIME * 0.6, POWER_UP_RESPAWN_TIME * 1.4
                )
                self.broadcast({"type": "powerup_expired", "pu_id": pu.pu_id})
                continue

            for plr in list(self.players.values()):
                if not plr.alive:
                    continue
                if (plr.x < pu.spawn_x + 10 and plr.x + PLAYER_W > pu.spawn_x and
                        plr.y < pu.spawn_y + 10 and plr.y + PLAYER_H > pu.spawn_y):
                    pu.active        = False
                    pu.respawn_timer = random.uniform(
                        POWER_UP_RESPAWN_TIME * 0.6, POWER_UP_RESPAWN_TIME * 1.4
                    )
                    duration = POWER_UP_DURATIONS[pu.pu_type]
                    if pu.pu_type == "shield":
                        plr.shield_until = now + duration
                    elif pu.pu_type == "rapid_fire":
                        plr.rapid_fire_until = now + duration
                    self.broadcast({
                        "type": "powerup_pickup", "pu_id": pu.pu_id,
                        "pu_type": pu.pu_type, "player_id": plr.player_id,
                        "duration": duration,
                    })
                    break

    def _kill_player_env(self, player_id: int) -> None:
        """Kill a player due to the environment (fall off map, no killer)."""
        p = self.players.get(player_id)
        if not p or not p.alive:
            return
        p.alive         = False
        p.hp            = 0
        p.respawn_timer = RESPAWN_DELAY
        self._drop_weapon(p)
        self.broadcast({
            "type":      "player_killed",
            "victim_id": player_id,
            "killer_id": -1,
            "x": p.x, "y": p.y,
        })

    def tick_fall_deaths(self) -> None:
        """Kill players whose server-side y has gone below the map (fell off)."""
        for p in list(self.players.values()):
            if p.alive and p.y > 450:
                self._kill_player_env(p.player_id)

    def tick_respawns(self, dt: float) -> None:
        for p in list(self.players.values()):
            if not p.alive and p.respawn_timer > 0:
                p.respawn_timer -= dt
                if p.respawn_timer <= 0:
                    p.respawn_timer = 0.0
                    self._respawn_player(p.player_id)

    # ── World state ───────────────────────────────────────────────────────────

    def build_world_msg(self) -> dict:
        now = time.time()
        return {
            "type": "world",
            "team_kills": {str(k): v for k, v in self.team_kills.items()},
            "players": {
                str(pid): {
                    "x": p.x, "y": p.y, "vx": p.vx, "vy": p.vy,
                    "facing": p.facing, "team_id": p.team_id,
                    "team_color": TEAM_COLORS[p.team_id % len(TEAM_COLORS)],
                    "alive": p.alive, "name": p.name, "hp": p.hp,
                    "shield_active": now < p.shield_until,
                    "weapon": p.weapon, "coins": p.coins,
                    "reload_left": max(0.0, p.reload_until - now),
                    "kills": p.kills,
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
                    "type": pu.pu_type, "active": pu.active,
                    "lifetime": pu.lifetime_timer,
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
            "objects": {
                str(o.obj_id): {
                    "type": o.obj_type, "x": o.x, "y": o.y,
                    "hp": o.hp, "max_hp": o.max_hp, "alive": o.alive,
                }
                for o in self.objects.values()
            },
        }

    def check_win_condition(self) -> None:
        """Score-based win: first team to KILL_LIMIT kills wins."""
        if not self.game_started or KILL_LIMIT <= 0:
            return
        for team_id, kills in self.team_kills.items():
            if kills >= KILL_LIMIT:
                self.game_over = True
                self.broadcast({
                    "type": "game_over",
                    "winner_team": team_id,
                    "team_color": TEAM_COLORS[team_id % len(TEAM_COLORS)],
                    "team_kills": {str(k): v for k, v in self.team_kills.items()},
                })
                print(f"Game over! Team {team_id} wins with {kills} kills.")
                return

    def _respawn_player(self, player_id: int) -> None:
        p = self.players.get(player_id)
        if not p:
            return
        now   = time.time()
        p.x, p.y      = rand_player_pos()
        p.vx = p.vy   = 0.0
        p.alive           = True
        p.hp              = PLAYER_MAX_HP
        p.respawn_timer   = 0.0
        p.rapid_fire_until = 0.0   # clear rapid-fire on death
        # Brief invincibility so respawned players aren't immediately killed
        p.shield_until    = now + RESPAWN_SHIELD
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
            print(f"Player {player_id} ({p.name}) joined")
            self.send_to(player_id, {
                "type": "welcome", "player_id": player_id,
                "num_teams": NUM_TEAMS, "max_hp": PLAYER_MAX_HP,
            })
            self.broadcast(self._get_lobby_info())

        elif mtype == "select_team":
            p = self.players.get(player_id)
            if p and not self.game_started:
                tid = int(msg.get("team_id", 0))
                if 0 <= tid < NUM_TEAMS:
                    p.team_id = tid
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
                p.x         = float(msg.get("x",  p.x))
                p.y         = float(msg.get("y",  p.y))
                p.vx        = float(msg.get("vx", p.vx))
                p.vy        = float(msg.get("vy", p.vy))
                p.on_ground = bool(msg.get("on_ground", False))
                p.facing    = msg.get("facing", p.facing)

        elif mtype == "fell_off":
            if self.game_started:
                self._kill_player_env(player_id)

        elif mtype == "pick_weapon":
            if not self.game_started:
                return
            p = self.players.get(player_id)
            if not p or not p.alive:
                return
            drop_id = msg.get("drop_id")
            drop = self.dropped_weapons.get(drop_id)
            if not drop or drop.pickup_delay > 0:
                return
            # Server-side range check (50 px from player center to drop)
            dx = (p.x + PLAYER_W / 2) - (drop.x + PLAYER_W / 2)
            dy = (p.y + PLAYER_H / 2) - drop.y
            if dx * dx + dy * dy > 50 * 50:
                return
            self.dropped_weapons.pop(drop_id, None)
            p.weapon = drop.weapon_id
            self.broadcast({
                "type": "weapon_pickup",
                "drop_id": drop_id, "player_id": player_id,
                "weapon_id": drop.weapon_id,
            })

        elif mtype == "throw":
            if self.game_started:
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
            dy = p.y - (SHOP_Y - PLAYER_H)
            if dx * dx + dy * dy > SHOP_RADIUS ** 2:
                self.send_to(player_id, {"type": "buy_failed", "reason": "too_far"})
                return
            if p.coins < weapon["price"]:
                self.send_to(player_id, {"type": "buy_failed", "reason": "insufficient_coins"})
                return
            p.coins  -= weapon["price"]
            p.weapon  = weapon_id
            self.send_to(player_id, {
                "type": "weapon_bought", "weapon_id": weapon_id, "coins": p.coins
            })

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
            time.sleep(interval)
            with self.lock:
                if self.game_started and self.players:
                    self.tick_fall_deaths()
                    self.tick_respawns(interval)
                    self.tick_projectiles(interval)
                    self.tick_power_ups(interval)
                    self.tick_dropped_weapons(interval)
                    self.broadcast(self.build_world_msg())

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self, num_teams: int = NUM_TEAMS) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(MAX_PLAYERS)
        print(f"Server on {HOST}:{PORT}  (teams={num_teams}, kill_limit={KILL_LIMIT})")

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
            print(f"Connection from {addr}, id={pid}")
            threading.Thread(target=self.handle_client, args=(conn, pid), daemon=True).start()

        print("Server shutting down.")
        srv.close()
