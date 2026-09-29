from random import SystemRandom

ID = "millia"
VERSION = 1
LABEL = "米莉亚"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}
COMMANDS = {}


def record_swap(game, target):
    from ..state import require

    require(target is not None, "米莉亚每晚必须选择一名玩家换血")
    game["millia_swap"] = {"seat": target, "day": game["day"]}


def require_swap(game, sid, actions):
    from ..state import current, require

    has_target = any(s["id"] != sid and current(game, s) for s in game["seats"])
    require(
        any(a["ability"] == "swap" for a in actions) or not has_target,
        "米莉亚每晚必须选择一名玩家换血",
    )


def force_swap(game, events):
    """未提交换血时随机指向别席当前牌；无人可选时不强制。"""
    from ..state import current, log_event, notify, owner, role_card, seat, uid

    card = role_card(game, ID)
    night = game["night"]
    sid = owner(game, ID)["id"]
    actors = night.get("actors") or {}
    if not card["alive"] or not isinstance(actors, dict) or actors.get(sid) != card["id"]:
        return
    if any(a["seat_id"] == sid and a["ability"] == "swap" for a in night["actions"]):
        return
    options = [s["id"] for s in game["seats"] if s["id"] != sid and current(game, s)]
    if not options:
        return
    target = SystemRandom().choice(options)
    target_card = current(game, seat(game, target))
    assert target_card is not None
    record_swap(game, target)
    night["actions"].append(
        {
            "id": uid(),
            "seat_id": sid,
            "participant_id": seat(game, sid)["occupant_id"],
            "card_id": card["id"],
            "ability": "swap",
            "target_seat": target,
            "target_card": target_card["id"],
            "confirmed": True,
            "by_host": True,
            "forced": True,
            "title": f"{sid}号夜间选择",
        }
    )
    log_event(game, "system", f"米莉亚未提交换血，系统随机指定{target}号。")
    notify(game, events, f"你本夜未提交换血，系统已随机指定{target}号为目标。", [sid], "换血强制")


def substitute_candidate(game, attacks, protection=()):
    """仅当换血对象真的被本批致死攻击打倒，才返回致死攻击索引与对象。"""
    from ..resolution import damage_preview
    from .marg import loved_card_id
    from ..state import current, present, seat

    swap = game.get("millia_swap")
    if not swap or not swap.get("seat") or not present(game, ID):
        return None
    target = current(game, seat(game, swap["seat"]))
    if not target or target["id"] == loved_card_id(game):
        return None
    probe = damage_preview(game, attacks, protection)
    death = next((item for item in probe["deaths"] if item["target_card"] == target["id"]), None)
    if death is None or death.get("cause") in {"devotion", "execution", "challenge", "treasure"}:
        return None
    index = death.get("attack_index")
    return (index, target["id"]) if index is not None and 0 <= index < len(attacks) else None


def substitute(game, attacks, protection=(), *, record=True):
    """只改写确实致死的那一击；爱与庇护的优先级由核心预览裁定。"""
    at_night = game["phase"] in {"night", "night_coco", "night_review"}
    night = game["night"]
    if at_night and "millia" in night["reactions"]:
        return attacks
    candidate = substitute_candidate(game, attacks, protection)
    if candidate is None:
        return attacks
    index, target_id = candidate
    rewritten = [dict(attack) for attack in attacks]
    lethal = {
        key: value
        for key, value in rewritten[index].items()
        if key not in {"injury", "once_injury"}
    }
    rewritten[index] = {**lethal, "target_card": ID, "substituted_from": target_id}
    if at_night and record:
        night["reactions"].append(ID)
    return rewritten


def publish_substitute(game, events, source_card):
    """换血对象私密，仅向米莉亚本人投递替死提示。"""
    from ..state import notify, owner, passive_card_payload

    if not source_card or ID not in game["cards"] or source_card not in game["cards"]:
        return
    target = f"{owner(game, source_card)['id']}号"
    effect = f"你换血的{target}本应出局，已由你代替出局。"
    notify(
        game,
        events,
        effect,
        [owner(game, ID)["id"]],
        "米莉亚替死",
        payload=passive_card_payload(game, "substitute", effect),
    )
