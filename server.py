#!/usr/bin/env python3
"""Root launcher for the game server.

Usage:
    python server.py          # 3 teams (default)
    python server.py 2        # 2 teams
"""
from src.server.main import run

if __name__ == "__main__":
    run()
