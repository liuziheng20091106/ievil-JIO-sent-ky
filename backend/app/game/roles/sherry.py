ID = "sherry"
VERSION = 1
LABEL = "雪莉"
REQUIRED = True
LAYER = "role"
DEPENDS = ()


def bound_now(game):
    """已绑定且两张牌仍存活；解绑后保留历史绑定标记。"""
    return (
        game["spiritual"]["sherry_bound"]
        and game["cards"][ID]["alive"]
        and game["cards"]["hanna"]["alive"]
    )


def bind(game, events, text):
    from ..state import notify, owner, passive_card_payload

    game["spiritual"]["sherry_bound"] = True
    notify(
        game,
        events,
        text,
        [owner(game, ID)["id"]],
        "雪莉绑定",
        payload=passive_card_payload(game, "bind", text),
    )


def start_binding(game, events):
    from ..state import current, owner

    if (
        current(game, owner(game, "hanna")) == game["cards"]["hanna"]
        and current(game, owner(game, ID)) == game["cards"][ID]
    ):
        bind(game, events, "你与汉娜均为上层，绑定自开局生效：胜负跟随汉娜，不能同意处决汉娜。")


def phase_enter(game, events, context):
    from ..state import present

    if context["from"] == "night_results" and context["to"] == "speech":
        game["day_binding"] = (
            {"day": game["day"], "intact": True}
            if present(game, ID) and present(game, "hanna")
            else None
        )


def finish_day_binding(game, events):
    from ..state import present

    binding = game["day_binding"]
    if binding and binding["intact"] and present(game, ID) and present(game, "hanna"):
        bind(game, events, "你与汉娜已共同度过完整白天，绑定生效。")


def invalidate_day(game):
    if game.get("day_binding"):
        game["day_binding"]["intact"] = False


def death_committed(game, events, context):
    if context["card_id"] in {ID, "hanna"}:
        invalidate_day(game)


def devotion(game, dead, guarded_seats):
    """仅汉娜被处决时殉情；同半天已出局的雪莉席位不再追加死亡。"""
    from ..state import owner

    if not (
        game["spiritual"]["sherry_bound"]
        and "hanna" in dead
        and dead["hanna"].get("cause") == "execution"
    ):
        return None
    sid = owner(game, ID)["id"]
    if not game["cards"][ID]["alive"] or sid in guarded_seats:
        return None
    return {
        "target_card": ID,
        "seat_id": sid,
        "cause": "devotion",
        "source_card": "hanna",
        "unconditional": True,
    }


HANDLERS = {"phase_enter": phase_enter, "death_committed": death_committed}
COMMANDS = {}
