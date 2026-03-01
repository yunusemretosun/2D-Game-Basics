"""Main game client."""
import json
import queue
import random
import socket
import sys
import threading
import time

import pygame
from pygame.locals import (
    QUIT, KEYDOWN, KEYUP, MOUSEBUTTONDOWN,
    K_ESCAPE, K_RIGHT, K_LEFT, K_UP, K_f, K_e,
    K_1, K_2, K_3, K_4, K_5,
)

from src.constants import (
    SERVER_HOST, SERVER_PORT,
    WINDOW_SIZE, DISPLAY_SIZE,
    TEAM_COLORS, TEAM_NAMES,
    POWER_UP_LIFETIME, DROPPED_WEAPON_LIFE,
    WEAPONS, WEAPON_COLORS,
    PU_COLORS, PU_FULL_NAMES,
    SHOP_X as _DEFAULT_SHOP_X,
    SHOP_Y as _DEFAULT_SHOP_Y,
    SHOP_RADIUS, TILE_SOLID,
    PLAYER_W, PLAYER_H,
)
import src.client.assets as assets
from src.client.renderer import (
    draw_background,
    draw_player, draw_dead_player, draw_hp_bar, draw_shield_aura,
    draw_power_up, draw_bullet, draw_dropped_weapon,
    draw_shop_sign, draw_shop_ui,
    draw_breakable_object,
    draw_lobby, draw_score_hud,
    Particle,
    spawn_hit_sparks, spawn_death_explosion, spawn_coin_burst,
    update_particles, draw_particles,
)

# ── Network helpers ───────────────────────────────────────────────────────────

def _send(sock, msg):
    try:
        sock.sendall((json.dumps(msg) + "\n").encode())
    except Exception:
        pass


def _recv_thread(sock, q):
    buf = ""
    while True:
        try:
            data = sock.recv(4096).decode()
            if not data:
                break
            buf += data
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line:
                    try:
                        q.put(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception:
            break


# ── Physics helpers ───────────────────────────────────────────────────────────

def _collision_test(rect, tiles):
    return [t for t in tiles if rect.colliderect(t)]


def _move(rect, movement, tiles):
    col = {"top": False, "bottom": False, "right": False, "left": False}
    rect.x += movement[0]
    for tile in _collision_test(rect, tiles):
        if movement[0] > 0:
            rect.right = tile.left;  col["right"] = True
        elif movement[0] < 0:
            rect.left  = tile.right; col["left"]  = True
    rect.y += movement[1]
    for tile in _collision_test(rect, tiles):
        if movement[1] > 0:
            rect.bottom = tile.top;  col["bottom"] = True
        elif movement[1] < 0:
            rect.top    = tile.bottom; col["top"]  = True
    return rect, col


# ── GameClient ────────────────────────────────────────────────────────────────

class GameClient:
    def __init__(self):
        self.sock        = None
        self.recv_q      = queue.Queue()
        self.player_id   = None
        self.player_name = f"Player{random.randint(1, 99)}"

        # Lobby / game
        self.num_teams     = 3
        self.max_hp        = 100
        self.my_team_id    = -1
        self.my_team_color = (255, 255, 255)
        self.my_ready      = False
        self.lobby_data    = None
        self.game_started  = False
        self.game_over_msg = None
        self.kill_limit    = 15

        # Local player
        self.player_rect        = pygame.Rect(100, 100, PLAYER_W, PLAYER_H)
        self.moving_right       = False
        self.moving_left        = False
        self.vertical_momentum  = 0.0
        self.air_timer          = 0
        self.true_scroll        = [0.0, 0.0]
        self.facing_dir         = "right"
        self.local_alive        = True
        self.local_hp           = 100
        self.anim_timer         = 0.0   # drives idle/run animation frames

        # Power-up effects
        self.active_effects         = {}
        self.mid_air_jump_available = False

        # Weapon state
        self.my_weapon       = "pistol"
        self.my_coins        = 30
        self.my_reload_until = 0.0
        self.firing          = False
        self.last_throw_time = 0.0
        self.shop_open       = False
        self.near_shop       = False
        self.shop_x          = _DEFAULT_SHOP_X
        self.shop_y          = _DEFAULT_SHOP_Y
        self._weapons        = dict(WEAPONS)

        # Remote world
        self.remote_players        = {}
        self.projectiles           = {}
        self.power_ups_world       = {}
        self.dropped_weapons_world = {}
        self.objects_world         = {}
        self.team_kills            = {}

        # Particles and effects
        self.particles: list[Particle] = []
        # hit-flash per player-id: {pid: expiry_timestamp}
        self.hit_flash: dict[str, float] = {}

        # UI feedback
        self.buy_error_msg   = ""
        self.buy_error_until = 0.0

        # Animation timers for remote players
        self.remote_anim: dict[str, float] = {}

        # Pygame
        self.screen  = None
        self.display = None
        self.clock   = None
        self._lobby_team_boxes = []
        self._lobby_ready_btn  = pygame.Rect(0, 0, 0, 0)

    # ── Startup ───────────────────────────────────────────────────────────────

    def connect(self):
        print(f"Connecting to {SERVER_HOST}:{SERVER_PORT} ...")
        try:
            self.sock = socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=10)
            self.sock.settimeout(None)
        except OSError as e:
            print(f"Could not connect: {e}")
            sys.exit(1)

        _send(self.sock, {"type": "join", "name": self.player_name})
        threading.Thread(target=_recv_thread, args=(self.sock, self.recv_q), daemon=True).start()

        print("Waiting for welcome...")
        deadline = time.time() + 10
        while self.player_id is None:
            try:
                msg = self.recv_q.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                print("Server not responding.")
                sys.exit(1)
            if msg.get("type") == "welcome":
                self.player_id = msg["player_id"]
                self.num_teams = msg.get("num_teams", 3)
                self.max_hp    = msg.get("max_hp", 100)
                self.local_hp  = self.max_hp
                print(f"Joined as {self.player_name} (id={self.player_id})")

    def init_pygame(self):
        pygame.init()
        pygame.display.set_caption(f"Battle Arena – {self.player_name}")
        self.screen  = pygame.display.set_mode(WINDOW_SIZE, 0, 32)
        self.display = pygame.Surface(DISPLAY_SIZE)
        self.clock   = pygame.time.Clock()
        assets.load_all()

    # ── Message processing ────────────────────────────────────────────────────

    def _drain_queue(self, now):
        while not self.recv_q.empty():
            msg   = self.recv_q.get_nowait()
            mtype = msg.get("type")

            if mtype == "lobby_update":
                self.lobby_data = msg

            elif mtype == "game_start":
                self.game_started = True
                self.player_rect.x = int(msg.get("spawn_x", 100))
                self.player_rect.y = int(msg.get("spawn_y", 100))
                self.vertical_momentum = 0.0
                self.air_timer         = 0
                self.local_alive       = True
                self.local_hp          = self.max_hp
                self.active_effects.clear()
                self.mid_air_jump_available = False
                self.my_team_color = tuple(TEAM_COLORS[self.my_team_id % len(TEAM_COLORS)])
                self.shop_x    = msg.get("shop_x", _DEFAULT_SHOP_X)
                self.shop_y    = msg.get("shop_y", _DEFAULT_SHOP_Y)
                self.kill_limit = msg.get("kill_limit", 15)
                self._weapons.update(msg.get("weapons", {}))
                self.my_weapon = "pistol"
                self.my_coins  = 30
                # Load breakable objects
                self.objects_world = msg.get("objects", {})
                pygame.display.set_caption(
                    f"Battle Arena – {self.player_name} "
                    f"(Team {TEAM_NAMES[self.my_team_id % len(TEAM_NAMES)]})"
                )

            elif mtype == "world":
                self.remote_players = {
                    k: v for k, v in msg["players"].items()
                    if k != str(self.player_id)
                }
                self.projectiles           = msg.get("projectiles", {})
                self.power_ups_world       = msg.get("power_ups", {})
                self.dropped_weapons_world = msg.get("dropped_weapons", {})
                self.team_kills            = msg.get("team_kills", {})
                # Update objects that are still alive
                for oid, od in msg.get("objects", {}).items():
                    self.objects_world[oid] = od

                my_data = msg["players"].get(str(self.player_id))
                if my_data:
                    self.local_hp  = my_data.get("hp", self.local_hp)
                    self.my_weapon = my_data.get("weapon", self.my_weapon)
                    self.my_coins  = my_data.get("coins", self.my_coins)

            elif mtype == "projectile_hit":
                victim_id = msg.get("victim_id")
                px, py    = msg.get("x", 0), msg.get("y", 0)

                # Spawn hit sparks
                if victim_id == self.player_id:
                    self.local_hp = msg.get("hp", self.local_hp)
                    spawn_hit_sparks(self.particles, self.player_rect.centerx,
                                     self.player_rect.centery,
                                     tuple(self.my_team_color))
                    self.hit_flash[str(self.player_id)] = now + 0.15
                else:
                    # Sparks at hit position
                    spawn_hit_sparks(self.particles, px, py, (255, 200, 100))
                    self.hit_flash[str(victim_id)] = now + 0.15

            elif mtype == "player_killed":
                victim_id = msg.get("victim_id")
                dx, dy    = msg.get("x", 0), msg.get("y", 0)
                is_me     = (victim_id == self.player_id)

                if is_me:
                    self.local_alive = False
                    self.local_hp    = 0
                    # Death explosion at local player position
                    spawn_death_explosion(self.particles,
                                         self.player_rect.centerx,
                                         self.player_rect.centery,
                                         tuple(self.my_team_color))
                else:
                    spawn_death_explosion(self.particles, dx, dy, (255, 100, 50))

            elif mtype == "object_hit":
                px, py = msg.get("x", 0), msg.get("y", 0)
                spawn_hit_sparks(self.particles, px, py, (180, 130, 60), count=4)
                oid = str(msg.get("obj_id"))
                if oid in self.objects_world:
                    self.objects_world[oid]["hp"] = msg.get("hp", 0)

            elif mtype == "object_destroyed":
                oid = str(msg.get("obj_id"))
                if oid in self.objects_world:
                    self.objects_world[oid]["alive"] = False
                ox, oy = msg.get("x", 0), msg.get("y", 0)
                spawn_coin_burst(self.particles, ox, oy)
                # Debris particles
                spawn_death_explosion(self.particles, ox, oy, (120, 80, 40), count=12)

            elif mtype == "respawn":
                if msg.get("player_id") == self.player_id:
                    self.player_rect.x     = int(msg["x"])
                    self.player_rect.y     = int(msg["y"])
                    self.vertical_momentum = 0.0
                    self.air_timer         = 0
                    self.local_alive       = True
                    self.local_hp          = msg.get("hp", self.max_hp)
                    self.my_weapon         = msg.get("weapon", "pistol")
                    self.my_coins          = msg.get("coins", self.my_coins)
                    self.my_reload_until   = 0.0
                    self.active_effects.clear()
                    self.mid_air_jump_available = False
                    self.shop_open = False

            elif mtype == "powerup_pickup":
                pu_type  = msg.get("pu_type", "speed")
                duration = msg.get("duration", 10.0)
                if msg.get("player_id") == self.player_id:
                    self.active_effects[pu_type] = now + duration
                    if pu_type == "double_jump":
                        self.mid_air_jump_available = True

            elif mtype == "weapon_bought":
                self.my_weapon       = msg.get("weapon_id", self.my_weapon)
                self.my_coins        = msg.get("coins", self.my_coins)
                self.my_reload_until = 0.0
                self.shop_open       = False

            elif mtype == "weapon_pickup":
                if msg.get("player_id") == self.player_id:
                    self.my_weapon       = msg.get("weapon_id", self.my_weapon)
                    self.my_reload_until = 0.0

            elif mtype == "coins_update":
                self.my_coins = msg.get("coins", self.my_coins)

            elif mtype == "buy_failed":
                reason = msg.get("reason", "")
                self.buy_error_msg   = "Too far from shop!" if reason == "too_far" else "Not enough coins!"
                self.buy_error_until = now + 2.5

            elif mtype == "weapon_gone":
                self.dropped_weapons_world.pop(str(msg.get("drop_id")), None)

            elif mtype == "game_over":
                self.game_over_msg = msg

            elif mtype == "player_left":
                self.remote_players.pop(str(msg.get("player_id")), None)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_nearby_dropped_weapon(self):
        """Return the drop_id (int) of the closest droppable weapon within 32 px,
        or None if nothing is nearby. Uses world coordinates."""
        if not self.local_alive:
            return None
        cx = self.player_rect.centerx
        cy = self.player_rect.centery
        best_id   = None
        best_dist = 32 * 32   # squared radius
        for did, dw in self.dropped_weapons_world.items():
            dx = dw["x"] + PLAYER_W // 2 - cx
            dy = dw["y"] - cy
            d2 = dx * dx + dy * dy
            if d2 <= best_dist:
                best_dist = d2
                best_id   = int(did)
        return best_id

    # ── Physics ───────────────────────────────────────────────────────────────

    def _step_physics(self, tile_rects, now):
        speed_mult = 2.0 if self.active_effects.get("speed", 0) > now else 1.0
        jump_mult  = 2.0 if self.active_effects.get("jump",  0) > now else 1.0

        moving = False
        mv = [0, 0]
        if self.moving_right:
            mv[0] += 2 * speed_mult
            self.facing_dir = "right"
            moving = True
        if self.moving_left:
            mv[0] -= 2 * speed_mult
            self.facing_dir = "left"
            moving = True
        mv[1] = self.vertical_momentum
        self.vertical_momentum = min(self.vertical_momentum + 0.2, 3)

        self.player_rect, col = _move(self.player_rect, mv, tile_rects)

        if col["bottom"]:
            self.air_timer        = 0
            self.vertical_momentum = 0
            if self.active_effects.get("double_jump", 0) > now:
                self.mid_air_jump_available = True
        else:
            self.air_timer += 1

        if self.player_rect.y > 500:
            if self.local_alive:
                self.local_alive = False
                _send(self.sock, {"type": "fell_off"})
                spawn_death_explosion(
                    self.particles,
                    self.player_rect.centerx, self.player_rect.centery,
                    tuple(self.my_team_color),
                )

        _send(self.sock, {
            "type":      "state",
            "x":         self.player_rect.x,
            "y":         self.player_rect.y,
            "vx":        mv[0],
            "vy":        self.vertical_momentum,
            "on_ground": bool(col.get("bottom", False)),
            "facing":    self.facing_dir,
        })
        return moving

    # ── Auto-fire ─────────────────────────────────────────────────────────────

    def _handle_autofire(self, now):
        if not (self.local_alive and self.firing and self._weapons):
            return
        w = self._weapons.get(self.my_weapon, {})
        if w.get("fire_mode") != "auto":
            return
        rapid    = self.active_effects.get("rapid_fire", 0) > now
        cooldown = w.get("reload_time", 0.4) * (0.33 if rapid else 1.0)
        if now - self.last_throw_time >= cooldown:
            self.last_throw_time  = now
            self.my_reload_until  = now + cooldown
            _send(self.sock, {"type": "throw", "facing": self.facing_dir})

    # ── Events ────────────────────────────────────────────────────────────────

    def _handle_events(self, now) -> bool:
        for event in pygame.event.get():
            if event.type == QUIT:
                return False
            if event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    if self.shop_open:
                        self.shop_open = False
                    else:
                        return False

                if not self.game_started:
                    continue

                if event.key == K_RIGHT:
                    self.moving_right = True
                if event.key == K_LEFT:
                    self.moving_left  = True

                if event.key == K_UP and self.local_alive and not self.shop_open:
                    jm = 2.0 if self.active_effects.get("jump", 0) > now else 1.0
                    if self.air_timer < 6:
                        self.vertical_momentum = -5 * jm
                    elif (self.mid_air_jump_available and
                          self.active_effects.get("double_jump", 0) > now):
                        self.vertical_momentum      = -5 * jm
                        self.mid_air_jump_available = False

                if event.key == K_f and self.local_alive and not self.shop_open:
                    self.firing = True
                    w = self._weapons.get(self.my_weapon, {})
                    if w.get("fire_mode") != "auto":
                        rapid     = self.active_effects.get("rapid_fire", 0) > now
                        effective = w.get("reload_time", 0.4) * (0.33 if rapid else 1.0)
                        if now - self.last_throw_time >= effective:
                            self.last_throw_time  = now
                            self.my_reload_until  = now + effective
                            _send(self.sock, {"type": "throw", "facing": self.facing_dir})

                if event.key == K_e and self.local_alive:
                    if self.shop_open:
                        self.shop_open = False
                    else:
                        drop_id = self._find_nearby_dropped_weapon()
                        if drop_id is not None:
                            _send(self.sock, {"type": "pick_weapon", "drop_id": drop_id})
                        elif self.near_shop:
                            self.shop_open = True

                if self.shop_open and self.local_alive and self._weapons:
                    wlist = list(self._weapons.keys())
                    for ki, kval in enumerate([K_1, K_2, K_3, K_4, K_5]):
                        if event.key == kval and ki < len(wlist):
                            _send(self.sock, {"type": "buy_weapon", "weapon_id": wlist[ki]})
                            break

            if event.type == KEYUP:
                if event.key == K_f:
                    self.firing       = False
                if event.key == K_RIGHT:
                    self.moving_right = False
                if event.key == K_LEFT:
                    self.moving_left  = False

            if event.type == MOUSEBUTTONDOWN and event.button == 1 and not self.game_started:
                mx = event.pos[0] * DISPLAY_SIZE[0] / WINDOW_SIZE[0]
                my = event.pos[1] * DISPLAY_SIZE[1] / WINDOW_SIZE[1]
                for t, box in enumerate(self._lobby_team_boxes):
                    if box.collidepoint(mx, my):
                        self.my_team_id = t
                        self.my_ready   = False
                        _send(self.sock, {"type": "select_team", "team_id": t})
                        break
                if self._lobby_ready_btn.collidepoint(mx, my) and self.my_team_id >= 0:
                    self.my_ready = not self.my_ready
                    _send(self.sock, {"type": "ready", "ready": self.my_ready})

        return True

    # ── Render ────────────────────────────────────────────────────────────────

    def _render_lobby(self):
        boxes, btn = draw_lobby(
            self.display, self.num_teams, self.my_team_id,
            self.my_ready, self.lobby_data,
        )
        self._lobby_team_boxes = boxes
        self._lobby_ready_btn  = btn

    def _render_game(self, now, dt):
        display = self.display

        # Camera
        self.true_scroll[0] += (self.player_rect.x - self.true_scroll[0] - 200) / 20
        self.true_scroll[1] += (self.player_rect.y - self.true_scroll[1] - 150) / 20
        scroll = [int(self.true_scroll[0]), int(self.true_scroll[1])]

        # Background
        draw_background(display, scroll)

        # Tiles
        tile_rects = []
        for ry, layer in enumerate(assets.game_map):
            for rx, tile in enumerate(layer):
                tx, ty = rx * 16 - scroll[0], ry * 16 - scroll[1]
                if -16 <= tx <= display.get_width() + 16 and -16 <= ty <= display.get_height() + 16:
                    img = assets.TILE_IMGS.get(tile)
                    if img:
                        display.blit(img, (tx, ty))
                if tile in TILE_SOLID:
                    tile_rects.append(pygame.Rect(rx * 16, ry * 16, 16, 16))

        # Breakable objects (behind players)
        for od in self.objects_world.values():
            if not od.get("alive", True):
                continue
            ox = int(od["x"]) - scroll[0]
            oy = int(od["y"]) - scroll[1]
            draw_breakable_object(display, ox, oy,
                                  od.get("type", "crate"),
                                  od.get("hp", 1), od.get("max_hp", 1))

        # Shop
        sx = self.shop_x - scroll[0]
        sy = self.shop_y - scroll[1]
        draw_shop_sign(display, sx, sy)
        ddx = self.player_rect.centerx - self.shop_x
        ddy = self.player_rect.centery - self.shop_y
        self.near_shop = (ddx * ddx + ddy * ddy) <= SHOP_RADIUS ** 2
        if self.near_shop and self.local_alive and not self.shop_open:
            hint = assets.font_small.render("[E] Open Shop", True, (255, 220, 80))
            display.blit(hint, (sx - hint.get_width() // 2, sy - 60))

        # Dropped weapons
        near_drop_id = self._find_nearby_dropped_weapon()
        for did, dw in self.dropped_weapons_world.items():
            draw_dropped_weapon(
                display,
                int(dw["x"]) - scroll[0], int(dw["y"]) - scroll[1],
                dw.get("weapon_id", "pistol"), dw.get("lifetime", DROPPED_WEAPON_LIFE),
                near=(did == str(near_drop_id)),
            )

        # Power-ups
        for pu in self.power_ups_world.values():
            if not pu.get("active"):
                continue
            draw_power_up(
                display,
                int(pu["x"]) - scroll[0], int(pu["y"]) - scroll[1],
                pu.get("type", "speed"), pu.get("lifetime", POWER_UP_LIFETIME),
            )

        # Auto-fire
        self._handle_autofire(now)

        # Local physics + animation
        moving = False
        if self.local_alive:
            moving = self._step_physics(tile_rects, now)
        self.anim_timer += dt

        # Local player
        px = self.player_rect.x - scroll[0]
        py = self.player_rect.y - scroll[1]
        flash_remain = max(0.0, self.hit_flash.get(str(self.player_id), 0) - now)
        if self.local_alive:
            if self.active_effects.get("shield", 0) > now:
                draw_shield_aura(display, px, py)
            draw_player(display, px, py,
                        self.my_team_id % 6, moving, self.anim_timer,
                        self.facing_dir, flash_remain)
            draw_hp_bar(display, px, py, self.local_hp, self.max_hp, self.my_team_id)
        else:
            draw_dead_player(display, px, py, self.my_team_id % 6)

        # Remote players
        for pid_str, rp in self.remote_players.items():
            rpx = int(rp["x"]) - scroll[0]
            rpy = int(rp["y"]) - scroll[1]
            tid = rp.get("team_id", 0) % 6

            # Update remote anim timer
            self.remote_anim[pid_str] = self.remote_anim.get(pid_str, 0.0) + dt
            rat = self.remote_anim[pid_str]
            rmoving = abs(rp.get("vx", 0)) > 0.5
            rfacing = rp.get("facing", "right")
            rflash  = max(0.0, self.hit_flash.get(pid_str, 0) - now)

            if not rp.get("alive", True):
                draw_dead_player(display, rpx, rpy, tid)
                continue
            if rp.get("shield_active"):
                draw_shield_aura(display, rpx, rpy)
            draw_player(display, rpx, rpy, tid, rmoving, rat, rfacing, rflash)
            draw_hp_bar(display, rpx, rpy, rp.get("hp", 0), self.max_hp, tid)
            ns = assets.font_small.render(rp.get("name", "?"), True, (255, 255, 255))
            display.blit(ns, (rpx - ns.get_width() // 2 + PLAYER_W // 2, rpy - 12))

        # Bullets
        for pr in self.projectiles.values():
            draw_bullet(
                display,
                int(pr["x"]) - scroll[0], int(pr["y"]) - scroll[1],
                pr.get("vx", 1), pr.get("vy", 0),
                pr.get("weapon_id", "pistol"),
            )

        # Particles
        update_particles(self.particles, dt)
        draw_particles(display, self.particles, scroll)

        # HUD
        self._draw_hud(display, now)

        if self.shop_open and self._weapons:
            draw_shop_ui(display, self.my_coins, self.my_weapon)

        if self.game_over_msg:
            self._draw_game_over(display)

        if not self.local_alive and not self.game_over_msg:
            dead = assets.font_small.render("DEAD – respawning...", True, (255, 80, 80))
            display.blit(dead, (200 - dead.get_width() // 2, 140))

    def _draw_hud(self, surf, now):
        # HP
        hp_txt = assets.font_med.render(f"HP: {self.local_hp}/{self.max_hp}", True, (255, 255, 255))
        surf.blit(hp_txt, (3, 3))
        bw, bh = 80, 6
        pygame.draw.rect(surf, (60, 60, 60), (3, 18, bw, bh))
        fw = int(bw * max(0, self.local_hp) / self.max_hp)
        if fw:
            frac = self.local_hp / self.max_hp
            bc = (0, 200, 0) if frac > 0.5 else (220, 180, 0) if frac > 0.25 else (220, 40, 40)
            pygame.draw.rect(surf, bc, (3, 18, fw, bh))

        # Active power-ups
        eff_y = 28
        for pu_type in ["speed", "jump", "shield", "rapid_fire", "double_jump"]:
            et = self.active_effects.get(pu_type, 0)
            if et > now:
                rem   = et - now
                color = PU_COLORS.get(pu_type, (255, 255, 255))
                pygame.draw.circle(surf, color, (8, eff_y + 4), 4)
                lbl = f"{PU_FULL_NAMES.get(pu_type, pu_type)} {rem:.1f}s"
                surf.blit(assets.font_small.render(lbl, True, color), (15, eff_y))
                eff_y += 11

        # Weapon
        wdata  = self._weapons.get(self.my_weapon, {})
        wname  = wdata.get("name", self.my_weapon)
        wcolor = WEAPON_COLORS.get(self.my_weapon, (200, 200, 200))
        surf.blit(assets.font_med.render(wname, True, wcolor), (3, eff_y + 2))
        if self.my_reload_until > now and wdata:
            rtotal = wdata.get("reload_time", 0.4)
            frac   = max(0.0, (self.my_reload_until - now) / rtotal)
            pygame.draw.rect(surf, (40, 40, 40), (3, eff_y + 14, 50, 3))
            rc = (255, 100, 40) if frac > 0.5 else (255, 220, 40)
            pygame.draw.rect(surf, rc, (3, eff_y + 14, max(1, int(50 * (1 - frac))), 3))
        surf.blit(assets.font_small.render(f"$ {self.my_coins}", True, (255, 215, 0)),
                  (3, eff_y + 20))

        # Buy error
        if self.buy_error_msg and self.buy_error_until > now:
            err = assets.font_small.render(self.buy_error_msg, True, (255, 80, 80))
            surf.blit(err, (200 - err.get_width() // 2, 170))

        # Kill scores
        draw_score_hud(surf, self.team_kills, self.my_team_id, self.kill_limit)

        # Controls hint
        hint = assets.font_small.render("[F] Fire  [E] Shop/Pick  [Arrows] Move", True, (180, 180, 180))
        surf.blit(hint, (200 - hint.get_width() // 2, 292))

    def _draw_game_over(self, surf):
        winner = self.game_over_msg.get("winner_team", -1)
        if winner == self.my_team_id:
            text, color = "Your team wins!", tuple(self.my_team_color)
        elif winner >= 0:
            color = tuple(self.game_over_msg.get("team_color", (200, 200, 200)))
            text  = f"Team {TEAM_NAMES[winner % len(TEAM_NAMES)]} wins!"
        else:
            text, color = "Draw!", (200, 200, 200)
        banner = assets.font_big.render(text, True, color)
        surf.blit(banner, (200 - banner.get_width() // 2, 125))
        sub = assets.font_small.render("Press ESC to quit", True, (255, 255, 255))
        surf.blit(sub, (200 - sub.get_width() // 2, 150))
        # Final scores
        y = 160
        for ts, kills in sorted(self.team_kills.items(), key=lambda x: -x[1]):
            tid = int(ts)
            col = tuple(TEAM_COLORS[tid % len(TEAM_COLORS)])
            s = assets.font_small.render(
                f"{TEAM_NAMES[tid % len(TEAM_NAMES)]}: {kills} kills", True, col)
            surf.blit(s, (200 - s.get_width() // 2, y))
            y += 11

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        prev = time.time()
        while True:
            now = time.time()
            dt  = min(now - prev, 0.05)
            prev = now

            self._drain_queue(now)

            if not self.game_started:
                self._render_lobby()
            else:
                self._render_game(now, dt)

            if not self._handle_events(now):
                break

            self.screen.blit(pygame.transform.scale(self.display, WINDOW_SIZE), (0, 0))
            pygame.display.update()
            self.clock.tick(60)

        pygame.quit()


def run():
    c = GameClient()
    c.connect()
    c.init_pygame()
    c.run()
