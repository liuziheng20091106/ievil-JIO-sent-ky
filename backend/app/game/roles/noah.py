ID = "noah"
VERSION = 1
LABEL = "诺亚"
REQUIRED = True
LAYER = "role"
DEPENDS = ()


def night_action(game, events, context):
    ability = context["ability"]
    if ability not in {"rain", "scapegoat"}:
        return
    card = game["cards"][context["card_id"]]
    if card["id"] != ID:
        return
    card["uses"][ability] = True
    if ability == "rain":
        game["night"]["rain"] = True
    else:
        action = next(
            item
            for item in game["night"]["actions"]
            if item["card_id"] == card["id"] and item["ability"] == ability
        )
        card["states"]["display_killer"] = action["target_card"]


HANDLERS = {"night_action": night_action}
COMMANDS = {}


def publish_footprints(game, events, death):
    """雨夜仅在真凶和死者异席时公开方向；汉娜凶手反转方向。"""
    from ..state import notify, owner

    source = death.get("source_card")
    if game["half"] != "night" or not game["night"].get("rain") or not source:
        return
    shown_source = game["cards"][source]["states"].get("display_killer", source)
    killer_seat = owner(game, shown_source)
    if killer_seat["id"] == death["seat_id"]:
        return
    rest = game["night"].get("rest") or {}
    if rest:
        text = (
            f"雨夜脚印：凶手{'是' if killer_seat['id'] == rest['seat_id'] else '不是'}"
            f"{rest['seat_id']}号（医务室方向）。"
        )
    else:
        greater = int(killer_seat["id"]) > int(death["seat_id"])
        if source == "hanna":
            greater = not greater
        text = f"雨夜脚印：凶手座位号{'大于' if greater else '小于'}死者座位号。"
    notify(game, events, text, title="雨夜脚印")
