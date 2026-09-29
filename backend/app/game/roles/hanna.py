ID = "hanna"
VERSION = 1
LABEL = "汉娜"
REQUIRED = True
LAYER = "role"
DEPENDS = ()


def witness_extra(game):
    """汉娜必须是存活的当前牌才使每份目击多一人并必含汉娜。"""
    from ..state import present

    return int(present(game, ID))


def witch_override(game):
    """第三夜覆盖魔女阵营人选的五项既定条件。"""
    from ..state import present
    from .sherry import bound_now

    return (
        bool(game.get("hanna_witch"))
        and present(game, ID)
        and game["spiritual"]["sherry_bound"]
        and not bound_now(game)
        and not present(game, "emma")
    )


def night_action(game, events, context):
    if context["card_id"] == ID and context["ability"] == "extra_kill":
        game["cards"][ID]["uses"]["extra_kill"] = True


def extra_attack(action, target):
    return {"target_card": target, "source_card": action["card_id"], "cause": "extra_kill"}


HANDLERS = {"night_action": night_action}
COMMANDS = {}
