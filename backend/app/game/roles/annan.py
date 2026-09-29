ID = "annan"
VERSION = 1
LABEL = "安安"
REQUIRED = True
LAYER = "role"
DEPENDS = ()


def night_action(game, events, context):
    if context["ability"] != "rest" or context["card_id"] != ID:
        return
    game["night"]["rest"] = {
        "seat_id": context["seat_id"],
        "card_id": context["card_id"],
        "day": game["day"],
    }


HANDLERS = {"night_action": night_action}
COMMANDS = {}


def publish_rest(game, events):
    from ..state import notify

    rest = game["night"].get("rest")

    if rest:
        notify(game, events, f"{rest['seat_id']}号今晚在医务室休息。", title="医务室休息")


def execute_declaration(game, events, declaration, target_card):
    """真洗脑与伪装洗脑共用效果；撤销仍由声明的核心质疑流程办理。"""
    from ..state import notify

    card = game["cards"][declaration["card_id"]]
    sid = declaration["seat_id"]
    target = declaration["data"]["target"]
    card["uses"]["mass_brainwash"] = True
    if target_card["id"] not in game["execution"]:
        game["execution"].append(target_card["id"])
    if card["id"] not in game["execution"]:
        game["execution"].append(card["id"])
    game["execution_lock"] = {"day": game["day"], "cards": [target_card["id"], card["id"]]}
    game["spiritual"]["annan_penalty"][sid] = {
        "day": game["day"],
        "declaration_id": declaration["id"],
        "self_card": card["id"],
    }
    declaration["effects"] = {
        "execution_card": target_card["id"],
        "self_execution_card": card["id"],
        "penalty_seat": sid,
    }
    notify(
        game,
        events,
        f"洗脑生效：{target}号与{sid}号一同进入今天的处决名单，今天不再处决其他人。",
    )
