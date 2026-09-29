"""Pure Python game API; persistence and transport are deliberately external."""

from .catalog import CATALOG, DEFAULT_CODEX
from .engine import (
    apply_command,
    expire_warnings,
    run_auto_advance,
    run_speech_timer,
    touch_speech_timer,
)
from .state import GameError, clear_seat_actions, create_game
from .views import game_view

__all__ = [
    "CATALOG",
    "DEFAULT_CODEX",
    "GameError",
    "apply_command",
    "clear_seat_actions",
    "create_game",
    "expire_warnings",
    "game_view",
    "run_auto_advance",
    "run_speech_timer",
    "touch_speech_timer",
]
