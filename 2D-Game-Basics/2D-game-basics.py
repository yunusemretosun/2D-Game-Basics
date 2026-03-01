import pygame, sys, socket, json, threading, queue, time
from pygame.locals import *

# ── Network config ────────────────────────────────────────────────────────────
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5555

TEAM_COLORS = [
    (220, 60,  60),
    (60,  100, 220),
    (60,  200, 60),
    (220, 180, 50),
    (180, 60,  220),
    (60,  200, 200),
]
TEAM_NAMES = ["Red", "Blue", "Green", "Yellow", "Purple", "Cyan"]

POWER_UP_LIFETIME = 12.0  # must match server POWER_UP_LIFETIME

# ── Weapon system (mirrors server) ────────────────────────────────────────────
SHOP_X      = 464   # world-pixel x center of shop (filled in from game_start)
SHOP_Y      = 256   # world-pixel y (top of center platform tile)
SHOP_RADIUS = 55

DROPPED_WEAPON_LIFE = 20.0  # must match server

WEAPONS = {}   # filled from server's game_start message

# Local weapon display data (visual constants only, not gameplay)
WEAPON_COLORS = {
    "pistol":    (210, 210, 210),
    "auto":      (255, 200,  50),
    "semi_auto": ( 80, 200, 255),
    "sniper":    (255,  50,  50),
    "shotgun":   (255, 140,  40),
}
WEAPON_BULLET_SIZE = {   # (trail_length, line_width)
    "pistol":    (6,  2),
    "auto":      (8,  2),
    "semi_auto": (8,  2),
    "sniper":    (14, 1),
    "shotgun":   (4,  3),
}

# ── Power-up visuals ──────────────────────────────────────────────────────────
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

# ── Network state ─────────────────────────────────────────────────────────────
my_player_id   = None
my_team_id     = -1
my_team_color  = (255, 255, 255)
num_teams      = 3
max_hp         = 100
remote_players = {}
projectiles    = {}
power_ups_world = {}
game_over_msg  = None
net_recv_queue = queue.Queue()
local_alive    = True
local_hp       = 100
lobby_data     = None
game_started   = False
my_ready       = False

last_throw_time = 0

# Local power-up effect timers  {type: expiry_timestamp}
active_effects = {}
mid_air_jump_available = False   # for double_jump ability

# ── Weapon state ──────────────────────────────────────────────────────────────
my_weapon         = "pistol"
my_coins          = 30
my_reload_until   = 0.0   # timestamp when player can shoot again
firing            = False  # K_f held (auto-fire)
fire_requested    = False  # K_f just pressed (semi)
shop_open         = False
near_shop         = False
dropped_weapons_world = {}
buy_error_msg     = ""
buy_error_until   = 0.0


def send_msg(sock, msg):
    try:
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
    except Exception:
        pass

def network_recv_thread(sock):
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
                        net_recv_queue.put(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception:
            break

# ── Connect to server ─────────────────────────────────────────────────────────
print(f"Connecting to {SERVER_HOST}:{SERVER_PORT} ...")
try:
    net_sock = socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=10)
    net_sock.settimeout(None)
except OSError as e:
    print(f"Could not connect: {e}")
    sys.exit(1)

player_name = f"Player{__import__('random').randint(1,99)}"
send_msg(net_sock, {"type": "join", "name": player_name})
threading.Thread(target=network_recv_thread, args=(net_sock,), daemon=True).start()

print("Waiting for server welcome...")
while my_player_id is None:
    try:
        msg = net_recv_queue.get(timeout=10.0)
    except queue.Empty:
        print("Server not responding. Exiting.")
        sys.exit(1)
    if msg["type"] == "welcome":
        my_player_id = msg["player_id"]
        num_teams    = msg.get("num_teams", 3)
        max_hp       = msg.get("max_hp", 100)
        local_hp     = max_hp
        print(f"Joined lobby as {player_name} (id={my_player_id})")

# ── Pygame init ───────────────────────────────────────────────────────────────
clock = pygame.time.Clock()
pygame.init()
pygame.display.set_caption(f'Battle Arena – {player_name}')

WINDOW_SIZE = (800, 600)
screen  = pygame.display.set_mode(WINDOW_SIZE, 0, 32)
display = pygame.Surface((400, 300))

font_small = pygame.font.SysFont(None, 14)
font_med   = pygame.font.SysFont(None, 20)
font_big   = pygame.font.SysFont(None, 32)

# ── Asset loading ─────────────────────────────────────────────────────────────
def load_map(path):
    with open(path + '.txt', 'r') as f:
        data = f.read()
    return [list(row) for row in data.split('\n') if row]

game_map = load_map('map')

grass_img  = pygame.image.load('grass.png')
dirt_img   = pygame.image.load('dirt.png')
player_img = pygame.image.load('player.png').convert()
player_img.set_colorkey((255, 255, 255))

# ── Game state ────────────────────────────────────────────────────────────────
player_rect      = pygame.Rect(100, 100, 5, 13)
moving_right     = False
moving_left      = False
vertical_momentum = 0
air_timer        = 0
true_scroll      = [0.0, 0.0]
facing_dir       = "right"

background_objects = [
    [0.25, [120, 10, 70, 500]],
    [0.25, [380, 30, 40, 500]],
    [0.5,  [30,  40, 40, 500]],
    [0.5,  [200, 90, 100, 500]],
    [0.5,  [450, 80, 120, 500]],
    [0.25, [600, 20, 60, 500]],
    [0.5,  [700, 60, 80, 500]],
]

# ── Physics helpers ───────────────────────────────────────────────────────────
def collision_test(rect, tiles):
    return [t for t in tiles if rect.colliderect(t)]

def move(rect, movement, tiles):
    col = {'top': False, 'bottom': False, 'right': False, 'left': False}
    rect.x += movement[0]
    for tile in collision_test(rect, tiles):
        if movement[0] > 0:
            rect.right = tile.left;  col['right'] = True
        elif movement[0] < 0:
            rect.left  = tile.right; col['left']  = True
    rect.y += movement[1]
    for tile in collision_test(rect, tiles):
        if movement[1] > 0:
            rect.bottom = tile.top;  col['bottom'] = True
        elif movement[1] < 0:
            rect.top    = tile.bottom; col['top']  = True
    return rect, col

# ── Drawing helpers ───────────────────────────────────────────────────────────
def draw_player(surf, img, x, y, color, alpha=160):
    surf.blit(img, (x, y))
    tint = pygame.Surface(img.get_size(), pygame.SRCALPHA)
    tint.fill((*color, alpha))
    surf.blit(tint, (x, y), special_flags=pygame.BLEND_RGBA_MULT)

def draw_hp_bar(surf, x, y, hp, max_hp_val, color):
    bar_w = 20
    bar_h = 3
    bx = x - bar_w // 2 + 2
    by = y - 5
    pygame.draw.rect(surf, (60, 60, 60), (bx, by, bar_w, bar_h))
    fill_w = int(bar_w * max(0, hp) / max_hp_val)
    if fill_w > 0:
        bar_color = (0, 200, 0) if hp > max_hp_val * 0.5 else (220, 180, 0) if hp > max_hp_val * 0.25 else (220, 40, 40)
        pygame.draw.rect(surf, bar_color, (bx, by, fill_w, bar_h))

def draw_power_up(surf, x, y, pu_type, lifetime=POWER_UP_LIFETIME):
    color = PU_COLORS.get(pu_type, (255, 255, 255))
    # Pulsing circle
    t = time.time()
    pulse = int(abs(((t * 3) % 2) - 1) * 2)  # 0-2 oscillation
    pygame.draw.circle(surf, color, (x + 5, y + 5), 6 + pulse)
    pygame.draw.circle(surf, (255, 255, 255), (x + 5, y + 5), 6 + pulse, 1)
    label = PU_LABELS.get(pu_type, "?")
    lbl_surf = font_small.render(label, True, (0, 0, 0))
    surf.blit(lbl_surf, (x + 5 - lbl_surf.get_width() // 2,
                         y + 5 - lbl_surf.get_height() // 2))
    # Lifetime bar: shrinks as power-up approaches expiry
    if 0 < lifetime < POWER_UP_LIFETIME:
        frac = max(0.0, lifetime / POWER_UP_LIFETIME)
        bar_color = (255, 60, 60) if frac < 0.3 else (255, 200, 0) if frac < 0.6 else (150, 255, 80)
        pygame.draw.rect(surf, (50, 50, 50), (x - 1, y + 13, 12, 2))
        pygame.draw.rect(surf, bar_color, (x - 1, y + 13, max(1, int(12 * frac)), 2))

def draw_shield_aura(surf, x, y):
    t = time.time()
    alpha = int(120 + 80 * abs(((t * 4) % 2) - 1))
    aura = pygame.Surface((26, 28), pygame.SRCALPHA)
    pygame.draw.ellipse(aura, (0, 180, 255, alpha), (0, 0, 26, 28), 2)
    surf.blit(aura, (x - 8, y - 6))


def draw_bullet(surf, x, y, vx, vy, weapon_id):
    """Draw a smooth elongated bullet with a trail."""
    color = WEAPON_COLORS.get(weapon_id, (220, 220, 220))
    length, width = WEAPON_BULLET_SIZE.get(weapon_id, (6, 2))
    speed = (vx * vx + vy * vy) ** 0.5
    if speed == 0:
        pygame.draw.circle(surf, color, (int(x), int(y)), width)
        return
    dx, dy = vx / speed, vy / speed
    tx, ty = int(x), int(y)
    tail_x, tail_y = int(x - dx * length), int(y - dy * length)
    # Trail (dimmer)
    trail = tuple(max(0, c // 3) for c in color)
    pygame.draw.line(surf, trail, (tx, ty), (tail_x, tail_y), max(1, width - 1))
    # Bright core (half length)
    mid_x, mid_y = int(x - dx * length // 2), int(y - dy * length // 2)
    pygame.draw.line(surf, color, (tx, ty), (mid_x, mid_y), width)
    # Tip highlight
    pygame.draw.circle(surf, (255, 255, 255), (tx, ty), max(1, width - 1))


def draw_dropped_weapon(surf, x, y, weapon_id, lifetime):
    """Draw a weapon pickup on the ground."""
    color = WEAPON_COLORS.get(weapon_id, (200, 200, 200))
    # Blink when about to expire
    if lifetime < 5.0 and int(time.time() * 5) % 2 == 0:
        return
    pygame.draw.rect(surf, color, (x, y, 12, 5))
    pygame.draw.rect(surf, (255, 255, 255), (x, y, 12, 5), 1)
    wname = WEAPONS.get(weapon_id, {}).get("name", weapon_id)
    lbl = font_small.render(wname, True, color)
    surf.blit(lbl, (x + 6 - lbl.get_width() // 2, y - 10))
    # Lifetime bar
    frac = max(0.0, lifetime / DROPPED_WEAPON_LIFE)
    bar_col = (255, 60, 60) if frac < 0.3 else (255, 200, 0) if frac < 0.6 else (100, 220, 100)
    pygame.draw.rect(surf, (40, 40, 40), (x - 1, y + 6, 14, 2))
    pygame.draw.rect(surf, bar_col, (x - 1, y + 6, max(1, int(14 * frac)), 2))


def draw_shop_sign(surf, wx, wy):
    """Draw the weapon shop building at world-pixel (wx, wy = floor y)."""
    # Building body
    pygame.draw.rect(surf, (100, 70, 40), (wx - 14, wy - 28, 28, 28))
    # Roof
    pygame.draw.polygon(surf, (160, 50, 50),
                        [(wx - 16, wy - 28), (wx, wy - 42), (wx + 16, wy - 28)])
    # Windows
    pygame.draw.rect(surf, (180, 220, 255), (wx - 11, wy - 24, 8, 7))
    pygame.draw.rect(surf, (180, 220, 255), (wx + 3,  wy - 24, 8, 7))
    # Door
    pygame.draw.rect(surf, (60, 35, 15), (wx - 4, wy - 14, 8, 14))
    # Sign
    sign_bg = pygame.Surface((26, 10), pygame.SRCALPHA)
    sign_bg.fill((240, 200, 40, 220))
    surf.blit(sign_bg, (wx - 13, wy - 44))
    sign_txt = font_small.render("SHOP", True, (20, 20, 20))
    surf.blit(sign_txt, (wx - sign_txt.get_width() // 2, wy - 44))


def draw_shop_ui(surf, coins, current_weapon):
    """Draw the weapon shop overlay."""
    # Dark panel
    panel = pygame.Surface((310, 210), pygame.SRCALPHA)
    panel.fill((10, 10, 30, 220))
    ox, oy = 45, 45
    surf.blit(panel, (ox, oy))
    pygame.draw.rect(surf, (200, 160, 40), (ox, oy, 310, 210), 2)

    title = font_med.render("WEAPON SHOP", True, (255, 200, 40))
    surf.blit(title, (ox + 155 - title.get_width() // 2, oy + 5))

    coin_surf = font_small.render(f"Coins: {coins}", True, (255, 215, 0))
    surf.blit(coin_surf, (ox + 5, oy + 22))

    close_hint = font_small.render("[E] Close", True, (160, 160, 160))
    surf.blit(close_hint, (ox + 305 - close_hint.get_width(), oy + 22))

    wlist = list(WEAPONS.items())
    for i, (wid, wdata) in enumerate(wlist):
        col_i = i % 2
        row_i = i // 2
        bx = ox + 8  + col_i * 153
        by = oy + 38 + row_i * 82

        is_owned   = (wid == current_weapon)
        can_afford = coins >= wdata["price"]

        bg = (30, 80, 30) if is_owned else (25, 25, 50)
        pygame.draw.rect(surf, bg, (bx, by, 145, 74), border_radius=4)
        border = (100, 220, 100) if is_owned else ((200, 200, 60) if can_afford else (80, 80, 80))
        pygame.draw.rect(surf, border, (bx, by, 145, 74), 1, border_radius=4)

        # Key hint
        key_surf = font_small.render(f"[{i+1}]", True, (180, 180, 180))
        surf.blit(key_surf, (bx + 3, by + 3))

        # Name + color swatch
        wcolor = WEAPON_COLORS.get(wid, (200, 200, 200))
        pygame.draw.rect(surf, wcolor, (bx + 20, by + 5, 10, 8))
        name_col = (180, 255, 180) if is_owned else (230, 230, 230)
        name_surf = font_small.render(wdata["name"], True, name_col)
        surf.blit(name_surf, (bx + 33, by + 3))
        if is_owned:
            eq = font_small.render("EQUIPPED", True, (100, 220, 100))
            surf.blit(eq, (bx + 145 - eq.get_width() - 3, by + 3))

        # Stats
        dmg_s = font_small.render(f"DMG {wdata['damage']}", True, (255, 110, 110))
        rng_s = font_small.render(f"RNG {wdata['range_px']}", True, (100, 190, 255))
        rl_s  = font_small.render(f"RPM {int(60/wdata['reload_time'])}", True, (210, 210, 120))
        mode_s = font_small.render(wdata["fire_mode"].upper(), True, (200, 160, 255))
        surf.blit(dmg_s,  (bx + 3, by + 18))
        surf.blit(rng_s,  (bx + 75, by + 18))
        surf.blit(rl_s,   (bx + 3, by + 30))
        surf.blit(mode_s, (bx + 75, by + 30))

        # Price
        if wdata["price"] == 0:
            price_str, price_col = "FREE", (80, 220, 80)
        else:
            price_str = f"{wdata['price']} coins"
            price_col = (255, 215, 0) if can_afford else (180, 60, 60)
        price_surf = font_small.render(price_str, True, price_col)
        surf.blit(price_surf, (bx + 3, by + 44))

def draw_lobby(surf):
    surf.fill((30, 30, 50))
    title = font_big.render("TEAM SELECTION", True, (255, 255, 255))
    surf.blit(title, (200 - title.get_width() // 2, 15))

    box_w = 110
    box_h = 150
    start_x = 200 - (num_teams * (box_w + 10)) // 2
    team_boxes = []
    for t in range(num_teams):
        bx = start_x + t * (box_w + 10)
        by = 50
        team_boxes.append(pygame.Rect(bx, by, box_w, box_h))
        color = TEAM_COLORS[t % len(TEAM_COLORS)]
        is_selected = (my_team_id == t)
        border_color = (255, 255, 255) if is_selected else (100, 100, 100)
        pygame.draw.rect(surf, (40, 40, 60), (bx, by, box_w, box_h))
        pygame.draw.rect(surf, border_color, (bx, by, box_w, box_h), 2)
        name = font_med.render(TEAM_NAMES[t % len(TEAM_NAMES)], True, color)
        surf.blit(name, (bx + box_w // 2 - name.get_width() // 2, by + 5))
        member_y = by + 25
        if lobby_data:
            for pid_str, pinfo in lobby_data.get("players", {}).items():
                if pinfo.get("team_id") == t:
                    pname = pinfo.get("name", "?")
                    ready_mark = " [OK]" if pinfo.get("ready") else ""
                    txt = font_small.render(f"{pname}{ready_mark}", True, (200, 200, 200))
                    surf.blit(txt, (bx + 5, member_y))
                    member_y += 12

    ready_color = (0, 180, 0) if my_ready else (120, 120, 120)
    ready_text = "READY!" if my_ready else "Click to Ready"
    if my_team_id < 0:
        ready_text = "Select a team first"
        ready_color = (80, 80, 80)
    ready_btn = pygame.Rect(200 - 70, 220, 140, 30)
    pygame.draw.rect(surf, ready_color, ready_btn, border_radius=4)
    pygame.draw.rect(surf, (200, 200, 200), ready_btn, 1, border_radius=4)
    rt = font_med.render(ready_text, True, (255, 255, 255))
    surf.blit(rt, (ready_btn.centerx - rt.get_width() // 2, ready_btn.centery - rt.get_height() // 2))

    inst = font_small.render("Click a team to join, then press Ready. Game starts when all players are ready.", True, (180, 180, 180))
    surf.blit(inst, (200 - inst.get_width() // 2, 260))

    pcount = len(lobby_data.get("players", {})) if lobby_data else 0
    pc_txt = font_small.render(f"Players in lobby: {pcount}", True, (150, 150, 150))
    surf.blit(pc_txt, (200 - pc_txt.get_width() // 2, 275))

    return team_boxes, ready_btn


# ── Main loop ─────────────────────────────────────────────────────────────────
while True:
    now = time.time()

    # ── Process network messages ──────────────────────────────────────────────
    while not net_recv_queue.empty():
        msg = net_recv_queue.get_nowait()
        mtype = msg.get("type")

        if mtype == "lobby_update":
            lobby_data = msg

        elif mtype == "game_start":
            game_started = True
            spawn_x = msg.get("spawn_x", 100)
            spawn_y = msg.get("spawn_y", 100)
            player_rect.x = int(spawn_x)
            player_rect.y = int(spawn_y)
            vertical_momentum = 0
            air_timer = 0
            local_alive = True
            local_hp = max_hp
            active_effects.clear()
            mid_air_jump_available = False
            my_team_color = TEAM_COLORS[my_team_id % len(TEAM_COLORS)]
            pygame.display.set_caption(f'Battle Arena – {player_name} (Team {TEAM_NAMES[my_team_id % len(TEAM_NAMES)]})')
            # Store server weapon data and shop position
            WEAPONS.update(msg.get("weapons", {}))
            SHOP_X = msg.get("shop_x", 464)
            SHOP_Y = msg.get("shop_y", 256)
            my_weapon = "pistol"
            my_coins  = 30
            print(f"Game started! Spawn at ({spawn_x}, {spawn_y})")

        elif mtype == "world":
            remote_players = {
                k: v for k, v in msg["players"].items()
                if k != str(my_player_id)
            }
            projectiles           = msg.get("projectiles", {})
            power_ups_world       = msg.get("power_ups", {})
            dropped_weapons_world = msg.get("dropped_weapons", {})
            my_data = msg["players"].get(str(my_player_id))
            if my_data:
                local_hp  = my_data.get("hp", local_hp)
                my_weapon = my_data.get("weapon", my_weapon)
                my_coins  = my_data.get("coins", my_coins)

        elif mtype == "projectile_hit":
            if msg.get("victim_id") == my_player_id:
                local_hp = msg.get("hp", local_hp)

        elif mtype == "player_killed":
            if msg.get("victim_id") == my_player_id:
                local_alive = False
                local_hp = 0
                print("You were killed! Waiting to respawn...")

        elif mtype == "respawn":
            if msg.get("player_id") == my_player_id:
                player_rect.x     = int(msg["x"])
                player_rect.y     = int(msg["y"])
                vertical_momentum = 0
                air_timer         = 0
                local_alive       = True
                local_hp          = msg.get("hp", max_hp)
                my_weapon         = msg.get("weapon", "pistol")
                my_coins          = msg.get("coins", my_coins)
                my_reload_until   = 0.0
                active_effects.clear()
                mid_air_jump_available = False
                shop_open = False
                print("Respawned!")

        elif mtype == "powerup_pickup":
            pu_type  = msg.get("pu_type", "speed")
            duration = msg.get("duration", 10.0)
            if msg.get("player_id") == my_player_id:
                active_effects[pu_type] = now + duration
                if pu_type == "double_jump":
                    mid_air_jump_available = True
                print(f"Picked up {pu_type} for {duration}s!")

        elif mtype == "weapon_bought":
            if True:  # sent only to buyer
                my_weapon = msg.get("weapon_id", my_weapon)
                my_coins  = msg.get("coins", my_coins)
                my_reload_until = 0.0
                shop_open = False
                print(f"Bought {my_weapon}! ({my_coins} coins left)")

        elif mtype == "weapon_pickup":
            if msg.get("player_id") == my_player_id:
                my_weapon = msg.get("weapon_id", my_weapon)
                my_reload_until = 0.0
                print(f"Picked up {my_weapon}!")

        elif mtype == "coins_update":
            my_coins = msg.get("coins", my_coins)

        elif mtype == "buy_failed":
            reason = msg.get("reason", "")
            buy_error_msg   = "Too far from shop!" if reason == "too_far" else "Not enough coins!"
            buy_error_until = now + 2.5

        elif mtype == "weapon_dropped":
            pass  # dropped_weapons_world updated via world msg

        elif mtype == "weapon_gone":
            dropped_weapons_world.pop(str(msg.get("drop_id")), None)

        elif mtype == "game_over":
            game_over_msg = msg

        elif mtype == "player_left":
            remote_players.pop(str(msg.get("player_id")), None)

    # ── LOBBY SCREEN ──────────────────────────────────────────────────────────
    if not game_started:
        team_boxes, ready_btn = draw_lobby(display)

        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit(); sys.exit()
            if event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    pygame.quit(); sys.exit()
            if event.type == MOUSEBUTTONDOWN and event.button == 1:
                mx = event.pos[0] * 400 / WINDOW_SIZE[0]
                my = event.pos[1] * 300 / WINDOW_SIZE[1]
                for t, box in enumerate(team_boxes):
                    if box.collidepoint(mx, my):
                        my_team_id = t
                        my_ready = False
                        send_msg(net_sock, {"type": "select_team", "team_id": t})
                        break
                if ready_btn.collidepoint(mx, my) and my_team_id >= 0:
                    my_ready = not my_ready
                    send_msg(net_sock, {"type": "ready", "ready": my_ready})

        screen.blit(pygame.transform.scale(display, WINDOW_SIZE), (0, 0))
        pygame.display.update()
        clock.tick(60)
        continue

    # ── GAME RENDERING ────────────────────────────────────────────────────────
    display.fill((146, 244, 255))

    true_scroll[0] += (player_rect.x - true_scroll[0] - 200) / 20
    true_scroll[1] += (player_rect.y - true_scroll[1] - 150) / 20
    scroll = [int(true_scroll[0]), int(true_scroll[1])]

    pygame.draw.rect(display, (7, 80, 75), pygame.Rect(0, 180, 400, 120))
    for obj in background_objects:
        ox = obj[1][0] - scroll[0] * obj[0]
        oy = obj[1][1] - scroll[1] * obj[0]
        color = (14, 222, 150) if obj[0] == 0.5 else (9, 91, 85)
        pygame.draw.rect(display, color, pygame.Rect(ox, oy, obj[1][2], obj[1][3]))

    tile_rects = []
    for y, layer in enumerate(game_map):
        for x, tile in enumerate(layer):
            tx, ty = x * 16 - scroll[0], y * 16 - scroll[1]
            if tile == '1':
                display.blit(dirt_img,  (tx, ty))
            elif tile == '2':
                display.blit(grass_img, (tx, ty))
            if tile != '0':
                tile_rects.append(pygame.Rect(x * 16, y * 16, 16, 16))

    # ── Draw weapon shop sign ─────────────────────────────────────────────────
    if game_started:
        sx = SHOP_X - scroll[0]
        sy = SHOP_Y - scroll[1]
        draw_shop_sign(display, sx, sy)
        # Proximity glow when near
        dx_shop = player_rect.x - SHOP_X
        dy_shop = player_rect.y - (SHOP_Y - 13)
        near_shop = (dx_shop * dx_shop + dy_shop * dy_shop) <= SHOP_RADIUS ** 2
        if near_shop and local_alive and not shop_open:
            hint_s = font_small.render("[E] Open Shop", True, (255, 220, 80))
            display.blit(hint_s, (sx - hint_s.get_width() // 2, sy - 56))

    # ── Draw dropped weapons ──────────────────────────────────────────────────
    for drop_str, dw in dropped_weapons_world.items():
        dwx = int(dw["x"]) - scroll[0]
        dwy = int(dw["y"]) - scroll[1]
        draw_dropped_weapon(display, dwx, dwy, dw.get("weapon_id", "pistol"),
                            dw.get("lifetime", DROPPED_WEAPON_LIFE))

    # ── Draw power-ups ────────────────────────────────────────────────────────
    for pu_id_str, pu in power_ups_world.items():
        if not pu.get("active"):
            continue
        pux = int(pu["x"]) - scroll[0]
        puy = int(pu["y"]) - scroll[1]
        draw_power_up(display, pux, puy, pu.get("type", "speed"), pu.get("lifetime", POWER_UP_LIFETIME))

    # ── Auto-fire (held K_f for auto weapons) ────────────────────────────────
    if local_alive and firing and WEAPONS:
        w = WEAPONS.get(my_weapon, {})
        if w.get("fire_mode") == "auto":
            rapid    = active_effects.get("rapid_fire", 0) > now
            cooldown = w.get("reload_time", 0.4) * (0.33 if rapid else 1.0)
            if now - last_throw_time >= cooldown:
                last_throw_time = now
                my_reload_until = now + cooldown
                send_msg(net_sock, {"type": "throw", "facing": facing_dir})

    # ── Local physics (only when alive) ───────────────────────────────────────
    if local_alive:
        speed_mult = 2.0 if active_effects.get("speed", 0) > now else 1.0
        jump_mult  = 2.0 if active_effects.get("jump",  0) > now else 1.0

        player_movement = [0, 0]
        if moving_right:
            player_movement[0] += 2 * speed_mult
            facing_dir = "right"
        if moving_left:
            player_movement[0] -= 2 * speed_mult
            facing_dir = "left"
        player_movement[1] = vertical_momentum
        vertical_momentum += 0.2
        if vertical_momentum > 3:
            vertical_momentum = 3

        player_rect, collisions = move(player_rect, player_movement, tile_rects)

        if collisions['bottom']:
            air_timer         = 0
            vertical_momentum = 0
            # Restore double-jump when landing
            if active_effects.get("double_jump", 0) > now:
                mid_air_jump_available = True
        else:
            air_timer += 1

        if player_rect.y > 450:
            local_alive = False

        send_msg(net_sock, {
            "type":      "state",
            "x":         player_rect.x,
            "y":         player_rect.y,
            "vx":        player_movement[0],
            "vy":        vertical_momentum,
            "on_ground": bool(collisions.get('bottom', False)),
            "facing":    facing_dir,
        })

    # ── Draw local player ─────────────────────────────────────────────────────
    px = player_rect.x - scroll[0]
    py = player_rect.y - scroll[1]
    if local_alive:
        if active_effects.get("shield", 0) > now:
            draw_shield_aura(display, px, py)
        draw_player(display, player_img, px, py, my_team_color)
        draw_hp_bar(display, px, py, local_hp, max_hp, my_team_color)
    else:
        ghost = pygame.Surface((5, 13), pygame.SRCALPHA)
        ghost.fill((*my_team_color, 60))
        display.blit(ghost, (px, py))

    # ── Draw remote players ───────────────────────────────────────────────────
    for pid_str, rp in remote_players.items():
        rpx = int(rp["x"]) - scroll[0]
        rpy = int(rp["y"]) - scroll[1]
        rp_color = tuple(rp.get("team_color", (200, 200, 200)))
        rp_hp = rp.get("hp", 0)
        if not rp.get("alive", True):
            ghost = pygame.Surface((5, 13), pygame.SRCALPHA)
            ghost.fill((*rp_color, 50))
            display.blit(ghost, (rpx, rpy))
            continue
        if rp.get("shield_active"):
            draw_shield_aura(display, rpx, rpy)
        draw_player(display, player_img, rpx, rpy, rp_color)
        draw_hp_bar(display, rpx, rpy, rp_hp, max_hp, rp_color)
        name_surf = font_small.render(rp.get("name", "?"), True, (255, 255, 255))
        display.blit(name_surf, (rpx - name_surf.get_width() // 2 + 2, rpy - 12))

    # ── Draw projectiles (smooth elongated bullets) ───────────────────────────
    for pid_str, pr in projectiles.items():
        prx = int(pr["x"]) - scroll[0]
        pry = int(pr["y"]) - scroll[1]
        draw_bullet(display, prx, pry,
                    pr.get("vx", 1), pr.get("vy", 0),
                    pr.get("weapon_id", "pistol"))

    # ── HUD ───────────────────────────────────────────────────────────────────
    hp_text = font_med.render(f"HP: {local_hp}/{max_hp}", True, (255, 255, 255))
    display.blit(hp_text, (3, 3))
    bar_w = 80
    bar_h = 6
    pygame.draw.rect(display, (60, 60, 60), (3, 18, bar_w, bar_h))
    fill_w = int(bar_w * max(0, local_hp) / max_hp)
    if fill_w > 0:
        bar_color = (0, 200, 0) if local_hp > max_hp * 0.5 else (220, 180, 0) if local_hp > max_hp * 0.25 else (220, 40, 40)
        pygame.draw.rect(display, bar_color, (3, 18, fill_w, bar_h))

    # Active power-up timers
    eff_y = 28
    for pu_type in ["speed", "jump", "shield", "rapid_fire", "double_jump"]:
        end_t = active_effects.get(pu_type, 0)
        if end_t > now:
            remaining = end_t - now
            color = PU_COLORS.get(pu_type, (255, 255, 255))
            pygame.draw.circle(display, color, (8, eff_y + 4), 4)
            label_str = f"{PU_FULL_NAMES.get(pu_type, pu_type)} {remaining:.1f}s"
            eff_txt = font_small.render(label_str, True, color)
            display.blit(eff_txt, (15, eff_y))
            eff_y += 11

    # Weapon & coins HUD
    wdata = WEAPONS.get(my_weapon, {})
    wname = wdata.get("name", my_weapon)
    wcolor = WEAPON_COLORS.get(my_weapon, (200, 200, 200))
    weap_surf = font_med.render(f"{wname}", True, wcolor)
    display.blit(weap_surf, (3, eff_y + 2))
    # Reload bar
    if my_reload_until > now and wdata:
        reload_total = wdata.get("reload_time", 0.4)
        frac = max(0.0, (my_reload_until - now) / reload_total)
        pygame.draw.rect(display, (40, 40, 40), (3, eff_y + 14, 50, 3))
        reload_col = (255, 100, 40) if frac > 0.5 else (255, 220, 40)
        pygame.draw.rect(display, reload_col, (3, eff_y + 14, max(1, int(50 * (1 - frac))), 3))
    # Coins
    coin_surf = font_small.render(f"$ {my_coins}", True, (255, 215, 0))
    display.blit(coin_surf, (3, eff_y + 20))

    # Buy error message
    if buy_error_msg and buy_error_until > now:
        err_surf = font_small.render(buy_error_msg, True, (255, 80, 80))
        display.blit(err_surf, (200 - err_surf.get_width() // 2, 170))

    hint = font_small.render("[F] Fire  [E] Shop  [Arrows] Move/Jump", True, (200, 200, 200))
    display.blit(hint, (400 - hint.get_width() - 3, 3))

    # ── Weapon shop overlay ───────────────────────────────────────────────────
    if shop_open and WEAPONS:
        draw_shop_ui(display, my_coins, my_weapon)

    # ── Game over banner ──────────────────────────────────────────────────────
    if game_over_msg:
        winner = game_over_msg.get("winner_team", -1)
        if winner == my_team_id:
            text = "Your team wins!"
            color = my_team_color
        elif winner >= 0:
            color = tuple(game_over_msg.get("team_color", (200, 200, 200)))
            text = f"Team {TEAM_NAMES[winner % len(TEAM_NAMES)]} wins!"
        else:
            text = "Draw!"; color = (200, 200, 200)
        banner = font_big.render(text, True, color)
        bx = 200 - banner.get_width() // 2
        display.blit(banner, (bx, 130))
        sub = font_small.render("Press ESC to quit", True, (255, 255, 255))
        display.blit(sub, (200 - sub.get_width() // 2, 155))

    if not local_alive and not game_over_msg:
        dead_surf = font_small.render("DEAD - respawning...", True, (255, 80, 80))
        display.blit(dead_surf, (200 - dead_surf.get_width() // 2, 140))

    # ── Event handling ────────────────────────────────────────────────────────
    for event in pygame.event.get():
        if event.type == QUIT:
            pygame.quit(); sys.exit()
        if event.type == KEYDOWN:
            if event.key == K_ESCAPE:
                if shop_open:
                    shop_open = False
                else:
                    pygame.quit(); sys.exit()
            if event.key == K_RIGHT:
                moving_right = True
            if event.key == K_LEFT:
                moving_left = True
            if event.key == K_UP:
                if local_alive and not shop_open:
                    jump_mult = 2.0 if active_effects.get("jump", 0) > now else 1.0
                    if air_timer < 6:
                        vertical_momentum = -5 * jump_mult
                    elif mid_air_jump_available and active_effects.get("double_jump", 0) > now:
                        vertical_momentum = -5 * jump_mult
                        mid_air_jump_available = False
            if event.key == K_f:
                if local_alive and not shop_open:
                    firing = True
                    w = WEAPONS.get(my_weapon, {})
                    if w.get("fire_mode") != "auto":
                        # Semi / shotgun / sniper: one shot per press
                        cooldown = w.get("reload_time", 0.4)
                        rapid = active_effects.get("rapid_fire", 0) > now
                        effective_cd = cooldown * (0.33 if rapid else 1.0)
                        if now - last_throw_time >= effective_cd:
                            last_throw_time = now
                            my_reload_until = now + effective_cd
                            send_msg(net_sock, {"type": "throw", "facing": facing_dir})
            # Shop number keys [1]-[5] for buying
            if shop_open and local_alive and WEAPONS:
                wlist = list(WEAPONS.keys())
                for ki, kval in enumerate([K_1, K_2, K_3, K_4, K_5]):
                    if event.key == kval and ki < len(wlist):
                        send_msg(net_sock, {
                            "type": "buy_weapon",
                            "weapon_id": wlist[ki],
                        })
                        break
            # E key: toggle shop
            if event.key == K_e and game_started and local_alive:
                if shop_open:
                    shop_open = False
                elif near_shop:
                    shop_open = True
        if event.type == KEYUP:
            if event.key == K_f:
                firing = False
            if event.key == K_RIGHT:
                moving_right = False
            if event.key == K_LEFT:
                moving_left = False

    screen.blit(pygame.transform.scale(display, WINDOW_SIZE), (0, 0))
    pygame.display.update()
    clock.tick(60)
