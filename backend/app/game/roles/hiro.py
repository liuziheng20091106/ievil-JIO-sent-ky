ID = "hiro"
VERSION = 1
LABEL = "希罗"
REQUIRED = True
LAYER = "role"
DEPENDS = ()


def target_snapshot(game, half):
    """夜回前一天顺序发言，昼回前一天自由发言，否则回开局。"""
    want = "speech" if half == "night" else "discussion"
    found = next(
        (
            snap
            for snap in game["snapshots"]
            if snap["day"] == game["day"] - 1 and snap["phase"] == want
        ),
        None,
    )
    return found or (game["snapshots"][0] if game["snapshots"] else None)


def rewind_on_death(game, events, half):
    """回溯成功后调用方必须终止本次阶段与伤害写入。"""
    from ..state import rewind

    if half == "night" and (game.get("night") or {}).get("massacre"):
        return False

    mode = "witch" if game["cards"][ID]["witch"] else "normal"
    if game["spiritual"]["hiro_used"][mode]:
        return False
    snap = target_snapshot(game, half)
    if snap is None:
        return False
    rewind(game, snap["id"], events, mode)
    game["rewound_night"] = True
    return True


def confirm_madness(game, card, actions, sid):
    """可攻击艾玛却没出手时消耗例外夜，或交主持裁定。"""
    from ..state import current, owner, pending
    from ..external_plugins.emma_treasure import treasure_protected
    from ..resolution import target_allowed

    emma = game["cards"]["emma"]
    can_attack = (
        emma["alive"]
        and current(game, owner(game, "emma")) == emma
        and target_allowed(game, "emma")
        and not treasure_protected(game, "emma")
    )
    attacked = any(
        action["ability"] == "knife" and action.get("target_card") == "emma" for action in actions
    )
    if not can_attack or attacked:
        return
    if game["spiritual"]["hiro_exception"]:
        pending(
            game, "madness", f"魔女希罗（{sid}号）本夜未攻击艾玛，请裁定是否足够疯狂", seat_id=sid
        )
    else:
        game["spiritual"]["hiro_exception"] = True


def exit_command(game, actor, events, payload, *, by_host=False):
    from ..state import can_use_ability, current, player_seat, require
    from ..engine import apply_damage
    from ..resolution import prepare_night_preview, resolve_intents

    seat = player_seat(game, actor)
    card = current(game, seat)
    require(card is not None, "当前没有可行动角色")
    require(
        by_host or can_use_ability(game, card, bool(actor.get("puppet_controlled"))),
        "傀儡与失去技能的角色不能发动技能",
    )
    attack = {"target_card": card["id"], "cause": "voluntary", "unconditional": True}
    if game["half"] == "night" and game["phase"] in {"night", "night_coco", "night_review"}:
        game["night"].setdefault("extra_attacks", []).append(attack)
        if game["night"]["locked"]:
            prepare_night_preview(game, events)
    else:
        apply_damage(game, events, resolve_intents(game, events, [attack], substitute=False))


HANDLERS = {}
COMMANDS = {"hiro.exit": exit_command}
