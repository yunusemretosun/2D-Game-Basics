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

# ── Network state ─────────────────────────────────────────────────────────────
my_player_id   = None
my_team_id     = -1
my_team_color  = (255, 255, 255)
num_teams      = 3
max_hp         = 100
remote_players = {}
projectiles    = {}
game_over_msg  = None
net_recv_queue = queue.Queue()
local_alive    = True
local_hp       = 100
lobby_data     = None
game_started   = False
my_ready       = False

THROW_COOLDOWN = 0.4  # seconds between throws
last_throw_time = 0

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

def draw_lobby(surf):
    surf.fill((30, 30, 50))
    # Title
    title = font_big.render("TEAM SELECTION", True, (255, 255, 255))
    surf.blit(title, (200 - title.get_width() // 2, 15))

    # Team boxes
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
        # Team name
        name = font_med.render(TEAM_NAMES[t % len(TEAM_NAMES)], True, color)
        surf.blit(name, (bx + box_w // 2 - name.get_width() // 2, by + 5))
        # Members
        member_y = by + 25
        if lobby_data:
            for pid_str, pinfo in lobby_data.get("players", {}).items():
                if pinfo.get("team_id") == t:
                    pname = pinfo.get("name", "?")
                    ready_mark = " [OK]" if pinfo.get("ready") else ""
                    txt = font_small.render(f"{pname}{ready_mark}", True, (200, 200, 200))
                    surf.blit(txt, (bx + 5, member_y))
                    member_y += 12

    # Ready button
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

    # Instructions
    inst = font_small.render("Click a team to join, then press Ready. Game starts when all players are ready.", True, (180, 180, 180))
    surf.blit(inst, (200 - inst.get_width() // 2, 260))

    # Player count
    pcount = len(lobby_data.get("players", {})) if lobby_data else 0
    pc_txt = font_small.render(f"Players in lobby: {pcount}", True, (150, 150, 150))
    surf.blit(pc_txt, (200 - pc_txt.get_width() // 2, 275))

    return team_boxes, ready_btn


# ── Main loop ─────────────────────────────────────────────────────────────────
while True:
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
            my_team_color = TEAM_COLORS[my_team_id % len(TEAM_COLORS)]
            pygame.display.set_caption(f'Battle Arena – {player_name} (Team {TEAM_NAMES[my_team_id % len(TEAM_NAMES)]})')
            print(f"Game started! Spawn at ({spawn_x}, {spawn_y})")

        elif mtype == "world":
            remote_players = {
                k: v for k, v in msg["players"].items()
                if k != str(my_player_id)
            }
            projectiles = msg.get("projectiles", {})
            # Update own HP from server
            my_data = msg["players"].get(str(my_player_id))
            if my_data:
                local_hp = my_data.get("hp", local_hp)

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
                player_rect.x    = int(msg["x"])
                player_rect.y    = int(msg["y"])
                vertical_momentum = 0
                air_timer        = 0
                local_alive      = True
                local_hp         = msg.get("hp", max_hp)
                print("Respawned!")

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
                # Scale mouse from window to display coords
                mx = event.pos[0] * 400 / WINDOW_SIZE[0]
                my = event.pos[1] * 300 / WINDOW_SIZE[1]
                # Check team box clicks
                for t, box in enumerate(team_boxes):
                    if box.collidepoint(mx, my):
                        my_team_id = t
                        my_ready = False
                        send_msg(net_sock, {"type": "select_team", "team_id": t})
                        break
                # Check ready button
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

    # ── Local physics (only when alive) ───────────────────────────────────────
    if local_alive:
        player_movement = [0, 0]
        if moving_right:
            player_movement[0] += 2
            facing_dir = "right"
        if moving_left:
            player_movement[0] -= 2
            facing_dir = "left"
        player_movement[1] = vertical_momentum
        vertical_momentum += 0.2
        if vertical_momentum > 3:
            vertical_momentum = 3

        player_rect, collisions = move(player_rect, player_movement, tile_rects)

        if collisions['bottom']:
            air_timer         = 0
            vertical_momentum = 0
        else:
            air_timer += 1

        # Fall off map
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
        draw_player(display, player_img, rpx, rpy, rp_color)
        draw_hp_bar(display, rpx, rpy, rp_hp, max_hp, rp_color)
        name_surf = font_small.render(rp.get("name", "?"), True, (255, 255, 255))
        display.blit(name_surf, (rpx - name_surf.get_width() // 2 + 2, rpy - 12))

    # ── Draw projectiles ──────────────────────────────────────────────────────
    for pid_str, pr in projectiles.items():
        prx = int(pr["x"]) - scroll[0]
        pry = int(pr["y"]) - scroll[1]
        pr_color = TEAM_COLORS[pr.get("team_id", 0) % len(TEAM_COLORS)]
        pygame.draw.rect(display, pr_color, (prx, pry, 4, 4))
        pygame.draw.rect(display, (255, 255, 255), (prx, pry, 4, 4), 1)

    # ── HUD ───────────────────────────────────────────────────────────────────
    # HP display
    hp_text = font_med.render(f"HP: {local_hp}/{max_hp}", True, (255, 255, 255))
    display.blit(hp_text, (3, 3))
    # HP bar at top
    bar_w = 80
    bar_h = 6
    pygame.draw.rect(display, (60, 60, 60), (3, 18, bar_w, bar_h))
    fill_w = int(bar_w * max(0, local_hp) / max_hp)
    if fill_w > 0:
        bar_color = (0, 200, 0) if local_hp > max_hp * 0.5 else (220, 180, 0) if local_hp > max_hp * 0.25 else (220, 40, 40)
        pygame.draw.rect(display, bar_color, (3, 18, fill_w, bar_h))

    # Controls hint
    hint = font_small.render("[F] Throw  [Arrow Keys] Move/Jump", True, (200, 200, 200))
    display.blit(hint, (400 - hint.get_width() - 3, 3))

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

    # ── Dead label ────────────────────────────────────────────────────────────
    if not local_alive and not game_over_msg:
        dead_surf = font_small.render("DEAD - respawning...", True, (255, 80, 80))
        display.blit(dead_surf, (200 - dead_surf.get_width() // 2, 140))

    # ── Event handling ────────────────────────────────────────────────────────
    for event in pygame.event.get():
        if event.type == QUIT:
            pygame.quit(); sys.exit()
        if event.type == KEYDOWN:
            if event.key == K_ESCAPE:
                pygame.quit(); sys.exit()
            if event.key == K_RIGHT:
                moving_right = True
            if event.key == K_LEFT:
                moving_left = True
            if event.key == K_UP:
                if local_alive and air_timer < 6:
                    vertical_momentum = -5
            if event.key == K_f:
                if local_alive:
                    now = time.time()
                    if now - last_throw_time >= THROW_COOLDOWN:
                        last_throw_time = now
                        send_msg(net_sock, {"type": "throw", "facing": facing_dir})
        if event.type == KEYUP:
            if event.key == K_RIGHT:
                moving_right = False
            if event.key == K_LEFT:
                moving_left = False

    screen.blit(pygame.transform.scale(display, WINDOW_SIZE), (0, 0))
    pygame.display.update()
    clock.tick(60)
