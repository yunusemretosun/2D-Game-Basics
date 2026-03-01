"""Server entry point."""
import sys
from src.server.game import GameServer
from src.constants import NUM_TEAMS


def run():
    num_teams = int(sys.argv[1]) if len(sys.argv) >= 2 else NUM_TEAMS
    GameServer().run(num_teams=num_teams)


if __name__ == "__main__":
    run()
