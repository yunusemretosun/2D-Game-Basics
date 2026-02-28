import pygame, sys, socket, json, threading, queue
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

# ── Network state (filled after welcome message) ──────────────────────────────
my_player_id   = None
my_team_id     = None
my_team_color  = (255, 255, 255)
remote_players = {}        # {pid_str: player_dict}
team_lives     = {}        # {tid_str: int}
game_over_msg  = None
net_recv_queue = queue.Queue()
local_alive    = True

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

# ── Connect to server and wait for welcome ────────────────────────────────────
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
        my_player_id  = msg["player_id"]
        my_team_id    = msg["team_id"]
        my_team_color = tuple(msg["team_color"])
        team_lives    = {str(my_team_id): msg["lives"]}
        spawn_x       = msg.get("spawn_x", 100)
        spawn_y       = msg.get("spawn_y", 50)
        print(f"Joined as {player_name} (id={my_player_id}, team={my_team_id})")

# ── Pygame init ───────────────────────────────────────────────────────────────
clock = pygame.time.Clock()
pygame.init()
pygame.display.set_caption(f'Battle Royale – {player_name} (Team {my_team_id})')

WINDOW_SIZE = (600, 400)
screen  = pygame.display.set_mode(WINDOW_SIZE, 0, 32)
display = pygame.Surface((300, 200))

font_small = pygame.font.SysFont(None, 14)
font_big   = pygame.font.SysFont(None, 28)

# ── Game state ────────────────────────────────────────────────────────────────
moving_right     = False
moving_left      = False
vertical_momentum = 0
air_timer        = 0
true_scroll      = [0, 0]
player_movement  = [0, 0]
collisions       = {}

def load_map(path):
    with open(path + '.txt', 'r') as f:
        data = f.read()
    return [list(row) for row in data.split('\n')]

game_map = load_map('map')

grass_img  = pygame.image.load('grass.png')
dirt_img   = pygame.image.load('dirt.png')
player_img = pygame.image.load('player.png').convert()
player_img.set_colorkey((255, 255, 255))

player_rect = pygame.Rect(spawn_x, spawn_y, 5, 13)

background_objects = [
    [0.25, [120, 10, 70, 400]],
    [0.25, [280, 30, 40, 400]],
    [0.5,  [30,  40, 40, 400]],
    [0.5,  [130, 90, 100,400]],
    [0.5,  [300, 80, 120,400]],
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

# ── Draw a tinted player sprite ───────────────────────────────────────────────
def draw_player(surf, img, x, y, color, alpha=160):
    surf.blit(img, (x, y))
    tint = pygame.Surface(img.get_size(), pygame.SRCALPHA)
    tint.fill((*color, alpha))
    surf.blit(tint, (x, y), special_flags=pygame.BLEND_RGBA_MULT)

# ── HUD helpers ───────────────────────────────────────────────────────────────
def draw_hud(surf, team_lives_dict):
    hud_y = 3
    for tid_str, lives in sorted(team_lives_dict.items()):
        tid   = int(tid_str)
        color = TEAM_COLORS[tid % len(TEAM_COLORS)]
        label = font_small.render(f"T{tid}:", True, color)
        surf.blit(label, (2, hud_y))
        for i in range(lives):
            pygame.draw.circle(surf, color, (24 + i * 9, hud_y + 4), 3)
        hud_y += 12

# ── Game loop ─────────────────────────────────────────────────────────────────
while True:
    # ── Process network messages ─────────────────────────────────────────────
    while not net_recv_queue.empty():
        msg = net_recv_queue.get_nowait()
        mtype = msg.get("type")

        if mtype == "world":
            remote_players = {
                k: v for k, v in msg["players"].items()
                if k != str(my_player_id)
            }
            team_lives = msg.get("team_lives", team_lives)

        elif mtype == "stomp":
            team_lives = {str(k): v for k, v in msg.get("team_lives", {}).items()}
            if msg.get("victim_id") == my_player_id:
                local_alive = False
                print("You were stomped! Waiting to respawn...")

        elif mtype == "respawn":
            if msg.get("player_id") == my_player_id:
                player_rect.x    = int(msg["x"])
                player_rect.y    = int(msg["y"])
                vertical_momentum = 0
                air_timer        = 0
                local_alive      = True
                print("Respawned!")

        elif mtype == "game_over":
            game_over_msg = msg

        elif mtype == "player_left":
            remote_players.pop(str(msg.get("player_id")), None)

    # ── Rendering ────────────────────────────────────────────────────────────
    display.fill((146, 244, 255))

    true_scroll[0] += (player_rect.x - true_scroll[0] - 152) / 20
    true_scroll[1] += (player_rect.y - true_scroll[1] - 106) / 20
    scroll = [int(true_scroll[0]), int(true_scroll[1])]

    pygame.draw.rect(display, (7, 80, 75), pygame.Rect(0, 120, 300, 80))
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

    # ── Local physics (only when alive) ──────────────────────────────────────
    if local_alive:
        player_movement = [0, 0]
        if moving_right:
            player_movement[0] += 2
        if moving_left:
            player_movement[0] -= 2
        player_movement[1] += vertical_momentum
        vertical_momentum   += 0.2
        if vertical_momentum > 3:
            vertical_momentum = 3

        player_rect, collisions = move(player_rect, player_movement, tile_rects)

        if collisions['bottom']:
            air_timer         = 0
            vertical_momentum = 0
        else:
            air_timer += 1

        # Fall off map → server will handle respawn via stomp margin,
        # but also guard locally so player doesn't go infinitely down
        if player_rect.y > 250:
            local_alive = False

        # Send state to server
        send_msg(net_sock, {
            "type":      "state",
            "x":         player_rect.x,
            "y":         player_rect.y,
            "vx":        player_movement[0],
            "vy":        vertical_momentum,
            "on_ground": bool(collisions.get('bottom', False)),
            "facing":    "right" if moving_right else "left",
        })

    # ── Draw local player (tinted by team color) ──────────────────────────────
    if local_alive:
        draw_player(
            display, player_img,
            player_rect.x - scroll[0],
            player_rect.y - scroll[1],
            my_team_color,
        )
    else:
        # Show ghost / "dead" indicator at last position
        ghost = pygame.Surface((5, 13), pygame.SRCALPHA)
        ghost.fill((*my_team_color, 60))
        display.blit(ghost, (player_rect.x - scroll[0], player_rect.y - scroll[1]))

    # ── Draw remote players ───────────────────────────────────────────────────
    for pid_str, rp in remote_players.items():
        if not rp.get("alive", True):
            # Draw ghost
            ghost = pygame.Surface((5, 13), pygame.SRCALPHA)
            ghost.fill((*tuple(rp.get("team_color", [200,200,200])), 50))
            display.blit(ghost, (int(rp["x"]) - scroll[0], int(rp["y"]) - scroll[1]))
            continue
        draw_player(
            display, player_img,
            int(rp["x"]) - scroll[0],
            int(rp["y"]) - scroll[1],
            tuple(rp.get("team_color", (200, 200, 200))),
        )
        # Name tag
        name_surf = font_small.render(rp.get("name", "?"), True, (255, 255, 255))
        display.blit(name_surf, (int(rp["x"]) - scroll[0] - name_surf.get_width()//2 + 2,
                                  int(rp["y"]) - scroll[1] - 9))

    # ── HUD ───────────────────────────────────────────────────────────────────
    draw_hud(display, team_lives)

    # ── Game over banner ──────────────────────────────────────────────────────
    if game_over_msg:
        winner = game_over_msg.get("winner_team", -1)
        if winner == my_team_id:
            text = "Your team wins!"
            color = my_team_color
        elif winner >= 0:
            color = tuple(game_over_msg.get("team_color", (200, 200, 200)))
            text = f"Team {winner} wins!"
        else:
            text = "Draw!"; color = (200, 200, 200)
        banner = font_big.render(text, True, color)
        bx = 150 - banner.get_width() // 2
        display.blit(banner, (bx, 85))
        sub = font_small.render("Press ESC to quit", True, (255, 255, 255))
        display.blit(sub, (150 - sub.get_width() // 2, 105))

    # ── Dead label ────────────────────────────────────────────────────────────
    if not local_alive and not game_over_msg:
        dead_surf = font_small.render("DEAD – respawning...", True, (255, 80, 80))
        display.blit(dead_surf, (150 - dead_surf.get_width() // 2, 92))

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
        if event.type == KEYUP:
            if event.key == K_RIGHT:
                moving_right = False
            if event.key == K_LEFT:
                moving_left = False

    screen.blit(pygame.transform.scale(display, WINDOW_SIZE), (0, 0))
    pygame.display.update()
    clock.tick(60)
