"""Pure Python game API; persistence and transport are deliberately external."""

from .catalog import CATALOG, DEFAULT_CODEX
from .engine import apply_command, expire_warnings, run_auto_advance
from .state import GameError, clear_seat_actions, create_game
from .views import game_view

__all__ = [
    "CATALOG",
    "DEFAULT_CODEX",
    "GameError",
    "create_game",
    "apply_command",
    "game_view",
    "expire_warnings",
    "run_auto_advance",
    "clear_seat_actions",
]
