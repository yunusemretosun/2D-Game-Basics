"""Main game client: networking, physics loop, and rendering."""
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
    SHOP_RADIUS,
)
import src.client.assets as assets
from src.client.renderer import (
    draw_player, draw_hp_bar, draw_shield_aura,
    draw_power_up, draw_bullet, draw_dropped_weapon,
    draw_shop_sign, draw_shop_ui, draw_lobby,
)


# ── Network helpers ───────────────────────────────────────────────────────────

def _send(sock: socket.socket, msg: dict) -> None:
    try:
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
    except Exception:
        pass


def _recv_thread(sock: socket.socket, q: queue.Queue) -> None:
    buf = ""
    while True:
        try:
            data = sock.recv(4096).decode("utf-8")
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

def _collision_test(rect: pygame.Rect, tiles: list) -> list:
    return [t for t in tiles if rect.colliderect(t)]


def _move(rect: pygame.Rect, movement: list, tiles: list):
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
        # Network
        self.sock         = None
        self.recv_q       = queue.Queue()
        self.player_id    = None
        self.player_name  = f"Player{random.randint(1, 99)}"

        # Lobby / game state
        self.num_teams    = 3
        self.max_hp       = 100
        self.my_team_id   = -1
        self.my_team_color = (255, 255, 255)
        self.my_ready     = False
        self.lobby_data   = None
        self.game_started = False
        self.game_over_msg = None

        # Local player
        self.player_rect       = pygame.Rect(100, 100, 5, 13)
        self.moving_right      = False
        self.moving_left       = False
        self.vertical_momentum = 0
        self.air_timer         = 0
        self.true_scroll       = [0.0, 0.0]
        self.facing_dir        = "right"
        self.local_alive       = True
        self.local_hp          = 100

        # Power-up effects
        self.active_effects          = {}  # {type: expiry_timestamp}
        self.mid_air_jump_available  = False

        # Weapon state
        self.my_weapon      = "pistol"
        self.my_coins       = 30
        self.my_reload_until = 0.0
        self.firing         = False
        self.last_throw_time = 0.0
        self.shop_open      = False
        self.near_shop      = False
        self.shop_x         = _DEFAULT_SHOP_X
        self.shop_y         = _DEFAULT_SHOP_Y

        # Remote world
        self.remote_players       = {}
        self.projectiles          = {}
        self.power_ups_world      = {}
        self.dropped_weapons_world = {}

        # UI
        self.buy_error_msg   = ""
        self.buy_error_until = 0.0

        # Pygame surfaces
        self.screen  = None
        self.display = None
        self.clock   = None

        # Background parallax objects
        self.bg_objects = [
            [0.25, [120, 10, 70, 500]],
            [0.25, [380, 30, 40, 500]],
            [0.5,  [30,  40, 40, 500]],
            [0.5,  [200, 90, 100, 500]],
            [0.5,  [450, 80, 120, 500]],
            [0.25, [600, 20, 60, 500]],
            [0.5,  [700, 60, 80, 500]],
        ]

        # Working weapons dict (filled from server on game_start)
        self._weapons = dict(WEAPONS)

    # ── Startup ───────────────────────────────────────────────────────────────

    def connect(self) -> None:
        print(f"Connecting to {SERVER_HOST}:{SERVER_PORT} ...")
        try:
            self.sock = socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=10)
            self.sock.settimeout(None)
        except OSError as e:
            print(f"Could not connect: {e}")
            sys.exit(1)

        _send(self.sock, {"type": "join", "name": self.player_name})
        threading.Thread(target=_recv_thread, args=(self.sock, self.recv_q),
                         daemon=True).start()

        print("Waiting for server welcome...")
        deadline = time.time() + 10
        while self.player_id is None:
            try:
                msg = self.recv_q.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                print("Server not responding. Exiting.")
                sys.exit(1)
            if msg.get("type") == "welcome":
                self.player_id  = msg["player_id"]
                self.num_teams  = msg.get("num_teams", 3)
                self.max_hp     = msg.get("max_hp", 100)
                self.local_hp   = self.max_hp
                print(f"Joined lobby as {self.player_name} (id={self.player_id})")

    def init_pygame(self) -> None:
        pygame.init()
        pygame.display.set_caption(f"Battle Arena – {self.player_name}")
        self.screen  = pygame.display.set_mode(WINDOW_SIZE, 0, 32)
        self.display = pygame.Surface(DISPLAY_SIZE)
        self.clock   = pygame.time.Clock()
        assets.load_all()

    # ── Message processing ────────────────────────────────────────────────────

    def _drain_queue(self) -> None:
        now = time.time()
        while not self.recv_q.empty():
            msg   = self.recv_q.get_nowait()
            mtype = msg.get("type")

            if mtype == "lobby_update":
                self.lobby_data = msg

            elif mtype == "game_start":
                self.game_started = True
                self.player_rect.x = int(msg.get("spawn_x", 100))
                self.player_rect.y = int(msg.get("spawn_y", 100))
                self.vertical_momentum = 0
                self.air_timer         = 0
                self.local_alive       = True
                self.local_hp          = self.max_hp
                self.active_effects.clear()
                self.mid_air_jump_available = False
                self.my_team_color = tuple(TEAM_COLORS[self.my_team_id % len(TEAM_COLORS)])
                self.shop_x = msg.get("shop_x", _DEFAULT_SHOP_X)
                self.shop_y = msg.get("shop_y", _DEFAULT_SHOP_Y)
                self._weapons.update(msg.get("weapons", {}))
                self.my_weapon = "pistol"
                self.my_coins  = 30
                pygame.display.set_caption(
                    f"Battle Arena – {self.player_name} "
                    f"(Team {TEAM_NAMES[self.my_team_id % len(TEAM_NAMES)]})"
                )
                print(f"Game started! Spawn at ({self.player_rect.x}, {self.player_rect.y})")

            elif mtype == "world":
                self.remote_players = {
                    k: v for k, v in msg["players"].items()
                    if k != str(self.player_id)
                }
                self.projectiles           = msg.get("projectiles", {})
                self.power_ups_world       = msg.get("power_ups", {})
                self.dropped_weapons_world = msg.get("dropped_weapons", {})
                my_data = msg["players"].get(str(self.player_id))
                if my_data:
                    self.local_hp   = my_data.get("hp", self.local_hp)
                    self.my_weapon  = my_data.get("weapon", self.my_weapon)
                    self.my_coins   = my_data.get("coins", self.my_coins)

            elif mtype == "projectile_hit":
                if msg.get("victim_id") == self.player_id:
                    self.local_hp = msg.get("hp", self.local_hp)

            elif mtype == "player_killed":
                if msg.get("victim_id") == self.player_id:
                    self.local_alive = False
                    self.local_hp    = 0
                    print("You were killed! Waiting to respawn...")

            elif mtype == "respawn":
                if msg.get("player_id") == self.player_id:
                    self.player_rect.x     = int(msg["x"])
                    self.player_rect.y     = int(msg["y"])
                    self.vertical_momentum = 0
                    self.air_timer         = 0
                    self.local_alive       = True
                    self.local_hp          = msg.get("hp", self.max_hp)
                    self.my_weapon         = msg.get("weapon", "pistol")
                    self.my_coins          = msg.get("coins", self.my_coins)
                    self.my_reload_until   = 0.0
                    self.active_effects.clear()
                    self.mid_air_jump_available = False
                    self.shop_open = False
                    print("Respawned!")

            elif mtype == "powerup_pickup":
                pu_type  = msg.get("pu_type", "speed")
                duration = msg.get("duration", 10.0)
                if msg.get("player_id") == self.player_id:
                    self.active_effects[pu_type] = now + duration
                    if pu_type == "double_jump":
                        self.mid_air_jump_available = True
                    print(f"Picked up {pu_type} for {duration}s!")

            elif mtype == "weapon_bought":
                self.my_weapon       = msg.get("weapon_id", self.my_weapon)
                self.my_coins        = msg.get("coins", self.my_coins)
                self.my_reload_until = 0.0
                self.shop_open       = False
                print(f"Bought {self.my_weapon}! ({self.my_coins} coins left)")

            elif mtype == "weapon_pickup":
                if msg.get("player_id") == self.player_id:
                    self.my_weapon       = msg.get("weapon_id", self.my_weapon)
                    self.my_reload_until = 0.0
                    print(f"Picked up {self.my_weapon}!")

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

    # ── Physics ───────────────────────────────────────────────────────────────

    def _step_physics(self, tile_rects: list, now: float) -> None:
        speed_mult = 2.0 if self.active_effects.get("speed", 0) > now else 1.0
        jump_mult  = 2.0 if self.active_effects.get("jump",  0) > now else 1.0

        movement = [0, 0]
        if self.moving_right:
            movement[0] += 2 * speed_mult
            self.facing_dir = "right"
        if self.moving_left:
            movement[0] -= 2 * speed_mult
            self.facing_dir = "left"
        movement[1] = self.vertical_momentum
        self.vertical_momentum = min(self.vertical_momentum + 0.2, 3)

        self.player_rect, collisions = _move(self.player_rect, movement, tile_rects)

        if collisions["bottom"]:
            self.air_timer         = 0
            self.vertical_momentum = 0
            if self.active_effects.get("double_jump", 0) > now:
                self.mid_air_jump_available = True
        else:
            self.air_timer += 1

        if self.player_rect.y > 450:
            self.local_alive = False

        _send(self.sock, {
            "type":      "state",
            "x":         self.player_rect.x,
            "y":         self.player_rect.y,
            "vx":        movement[0],
            "vy":        self.vertical_momentum,
            "on_ground": bool(collisions.get("bottom", False)),
            "facing":    self.facing_dir,
        })

    # ── Auto-fire ─────────────────────────────────────────────────────────────

    def _handle_autofire(self, now: float) -> None:
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

    def _handle_events(self, now: float) -> bool:
        """Process pygame events. Returns False if the game should quit."""
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
                    continue  # only ESC handled before game

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
                        rapid       = self.active_effects.get("rapid_fire", 0) > now
                        effective   = w.get("reload_time", 0.4) * (0.33 if rapid else 1.0)
                        if now - self.last_throw_time >= effective:
                            self.last_throw_time  = now
                            self.my_reload_until  = now + effective
                            _send(self.sock, {"type": "throw", "facing": self.facing_dir})
                if event.key == K_e and self.local_alive:
                    if self.shop_open:
                        self.shop_open = False
                    elif self.near_shop:
                        self.shop_open = True

                # Shop number keys [1]–[5]
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

    def _render_lobby(self) -> None:
        team_boxes, ready_btn = draw_lobby(
            self.display, self.num_teams, self.my_team_id,
            self.my_ready, self.lobby_data,
        )
        self._lobby_team_boxes = team_boxes
        self._lobby_ready_btn  = ready_btn

    def _render_game(self, now: float) -> None:
        display = self.display

        display.fill((146, 244, 255))

        # Smooth camera follow
        self.true_scroll[0] += (self.player_rect.x - self.true_scroll[0] - 200) / 20
        self.true_scroll[1] += (self.player_rect.y - self.true_scroll[1] - 150) / 20
        scroll = [int(self.true_scroll[0]), int(self.true_scroll[1])]

        # Background
        pygame.draw.rect(display, (7, 80, 75), pygame.Rect(0, 180, 400, 120))
        for obj in self.bg_objects:
            ox = obj[1][0] - scroll[0] * obj[0]
            oy = obj[1][1] - scroll[1] * obj[0]
            col = (14, 222, 150) if obj[0] == 0.5 else (9, 91, 85)
            pygame.draw.rect(display, col, pygame.Rect(ox, oy, obj[1][2], obj[1][3]))

        # Tiles
        tile_rects = []
        for y, layer in enumerate(assets.game_map):
            for x, tile in enumerate(layer):
                tx, ty = x * 16 - scroll[0], y * 16 - scroll[1]
                if tile == "1":
                    display.blit(assets.dirt_img,  (tx, ty))
                elif tile == "2":
                    display.blit(assets.grass_img, (tx, ty))
                if tile != "0":
                    tile_rects.append(pygame.Rect(x * 16, y * 16, 16, 16))

        # Shop
        sx = self.shop_x - scroll[0]
        sy = self.shop_y - scroll[1]
        draw_shop_sign(display, sx, sy)
        dx_shop = self.player_rect.x - self.shop_x
        dy_shop = self.player_rect.y - (self.shop_y - 13)
        self.near_shop = (dx_shop * dx_shop + dy_shop * dy_shop) <= SHOP_RADIUS ** 2
        if self.near_shop and self.local_alive and not self.shop_open:
            hint = assets.font_small.render("[E] Open Shop", True, (255, 220, 80))
            display.blit(hint, (sx - hint.get_width() // 2, sy - 56))

        # Dropped weapons
        for dw in self.dropped_weapons_world.values():
            draw_dropped_weapon(
                display,
                int(dw["x"]) - scroll[0], int(dw["y"]) - scroll[1],
                dw.get("weapon_id", "pistol"), dw.get("lifetime", DROPPED_WEAPON_LIFE),
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

        # Auto-fire before physics
        self._handle_autofire(now)

        # Physics
        if self.local_alive:
            self._step_physics(tile_rects, now)

        # Local player
        px = self.player_rect.x - scroll[0]
        py = self.player_rect.y - scroll[1]
        if self.local_alive:
            if self.active_effects.get("shield", 0) > now:
                draw_shield_aura(display, px, py)
            draw_player(display, px, py, self.my_team_color)
            draw_hp_bar(display, px, py, self.local_hp, self.max_hp, self.my_team_color)
        else:
            ghost = pygame.Surface((5, 13), pygame.SRCALPHA)
            ghost.fill((*self.my_team_color, 60))
            display.blit(ghost, (px, py))

        # Remote players
        for rp in self.remote_players.values():
            rpx = int(rp["x"]) - scroll[0]
            rpy = int(rp["y"]) - scroll[1]
            rp_color = tuple(rp.get("team_color", (200, 200, 200)))
            if not rp.get("alive", True):
                ghost = pygame.Surface((5, 13), pygame.SRCALPHA)
                ghost.fill((*rp_color, 50))
                display.blit(ghost, (rpx, rpy))
                continue
            if rp.get("shield_active"):
                draw_shield_aura(display, rpx, rpy)
            draw_player(display, rpx, rpy, rp_color)
            draw_hp_bar(display, rpx, rpy, rp.get("hp", 0), self.max_hp, rp_color)
            name_s = assets.font_small.render(rp.get("name", "?"), True, (255, 255, 255))
            display.blit(name_s, (rpx - name_s.get_width() // 2 + 2, rpy - 12))

        # Bullets
        for pr in self.projectiles.values():
            draw_bullet(
                display,
                int(pr["x"]) - scroll[0], int(pr["y"]) - scroll[1],
                pr.get("vx", 1), pr.get("vy", 0),
                pr.get("weapon_id", "pistol"),
            )

        # HUD
        self._draw_hud(display, now)

        # Shop overlay
        if self.shop_open and self._weapons:
            draw_shop_ui(display, self.my_coins, self.my_weapon)

        # Game over banner
        if self.game_over_msg:
            self._draw_game_over(display)

        # Dead overlay
        if not self.local_alive and not self.game_over_msg:
            dead = assets.font_small.render("DEAD - respawning...", True, (255, 80, 80))
            display.blit(dead, (200 - dead.get_width() // 2, 140))

    def _draw_hud(self, surf: pygame.Surface, now: float) -> None:
        # HP bar
        hp_text = assets.font_med.render(f"HP: {self.local_hp}/{self.max_hp}", True, (255, 255, 255))
        surf.blit(hp_text, (3, 3))
        bar_w, bar_h = 80, 6
        pygame.draw.rect(surf, (60, 60, 60), (3, 18, bar_w, bar_h))
        fill_w = int(bar_w * max(0, self.local_hp) / self.max_hp)
        if fill_w > 0:
            if self.local_hp > self.max_hp * 0.5:
                bc = (0, 200, 0)
            elif self.local_hp > self.max_hp * 0.25:
                bc = (220, 180, 0)
            else:
                bc = (220, 40, 40)
            pygame.draw.rect(surf, bc, (3, 18, fill_w, bar_h))

        # Active power-up timers
        eff_y = 28
        for pu_type in ["speed", "jump", "shield", "rapid_fire", "double_jump"]:
            end_t = self.active_effects.get(pu_type, 0)
            if end_t > now:
                remaining = end_t - now
                color = PU_COLORS.get(pu_type, (255, 255, 255))
                pygame.draw.circle(surf, color, (8, eff_y + 4), 4)
                label = f"{PU_FULL_NAMES.get(pu_type, pu_type)} {remaining:.1f}s"
                eff_txt = assets.font_small.render(label, True, color)
                surf.blit(eff_txt, (15, eff_y))
                eff_y += 11

        # Weapon & coins
        wdata  = self._weapons.get(self.my_weapon, {})
        wname  = wdata.get("name", self.my_weapon)
        wcolor = WEAPON_COLORS.get(self.my_weapon, (200, 200, 200))
        weap_s = assets.font_med.render(wname, True, wcolor)
        surf.blit(weap_s, (3, eff_y + 2))
        if self.my_reload_until > now and wdata:
            reload_total = wdata.get("reload_time", 0.4)
            frac = max(0.0, (self.my_reload_until - now) / reload_total)
            pygame.draw.rect(surf, (40, 40, 40), (3, eff_y + 14, 50, 3))
            rc = (255, 100, 40) if frac > 0.5 else (255, 220, 40)
            pygame.draw.rect(surf, rc, (3, eff_y + 14, max(1, int(50 * (1 - frac))), 3))
        coin_s = assets.font_small.render(f"$ {self.my_coins}", True, (255, 215, 0))
        surf.blit(coin_s, (3, eff_y + 20))

        # Buy error
        if self.buy_error_msg and self.buy_error_until > now:
            err = assets.font_small.render(self.buy_error_msg, True, (255, 80, 80))
            surf.blit(err, (200 - err.get_width() // 2, 170))

        hint = assets.font_small.render("[F] Fire  [E] Shop  [Arrows] Move/Jump",
                                        True, (200, 200, 200))
        surf.blit(hint, (400 - hint.get_width() - 3, 3))

    def _draw_game_over(self, surf: pygame.Surface) -> None:
        winner = self.game_over_msg.get("winner_team", -1)
        if winner == self.my_team_id:
            text, color = "Your team wins!", self.my_team_color
        elif winner >= 0:
            color = tuple(self.game_over_msg.get("team_color", (200, 200, 200)))
            text  = f"Team {TEAM_NAMES[winner % len(TEAM_NAMES)]} wins!"
        else:
            text, color = "Draw!", (200, 200, 200)
        banner = assets.font_big.render(text, True, color)
        surf.blit(banner, (200 - banner.get_width() // 2, 130))
        sub = assets.font_small.render("Press ESC to quit", True, (255, 255, 255))
        surf.blit(sub, (200 - sub.get_width() // 2, 155))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._lobby_team_boxes = []
        self._lobby_ready_btn  = pygame.Rect(0, 0, 0, 0)

        while True:
            now = time.time()
            self._drain_queue()

            if not self.game_started:
                self._render_lobby()
            else:
                self._render_game(now)

            if not self._handle_events(now):
                break

            self.screen.blit(
                pygame.transform.scale(self.display, WINDOW_SIZE), (0, 0)
            )
            pygame.display.update()
            self.clock.tick(60)

        pygame.quit()


def run() -> None:
    client = GameClient()
    client.connect()
    client.init_pygame()
    client.run()
