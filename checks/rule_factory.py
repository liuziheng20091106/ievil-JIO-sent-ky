"""Deterministic seven-seat game setup for rule boundary checks only."""

from backend.app.game import DEFAULT_CODEX, apply_command, clock, create_game
from backend.app.game.state import start_phase

PAIRS = [
    ["millia", "emma"],
    ["hiro", "coco"],
    ["meruru", "hanna"],
    ["marg", "sherry"],
    ["leia", "arisa"],
    ["noah", "annan"],
    ["nanoka", "honoka"],
]


def player(game, sid):
    return {
        "id": "p" + sid,
        "kind": "player",
        "seat_id": sid,
        "game_id": game["id"],
        "access_ids": ["p" + sid],
    }


def arranged_game(phase="discussion", half="day"):
    game = create_game(DEFAULT_CODEX)
    for seat in game["seats"]:
        seat["occupant_id"] = "p" + seat["id"]
    for seat in game["seats"]:
        apply_command(game, player(game, seat["id"]), "lobby.ready", {})
    game.update(status="playing", phase=phase, half=half, day=2)
    start_phase(game, phase)
    for seat, pair in zip(game["seats"], PAIRS, strict=True):
        seat.update(cards=list(pair), occupant_id="p" + seat["id"], ready=True)
    return game


def force_after_wait(game, host):
    """旧规则检查需要强制放弃时，显式等满当前阶段的45秒保护。"""
    fake = clock.FakeClock(clock.now())
    with fake.installed():
        fake.advance_to(game["public"]["phase_started_at"] + 45)
        return apply_command(game, host, "host.advance", {})
