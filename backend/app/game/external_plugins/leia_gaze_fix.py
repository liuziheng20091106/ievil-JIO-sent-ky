"""蕾雅每日一次的全场动画，不参与技能声明与规则结算。"""

from ..state import can_use_ability, current, display_player_name, notify, player_seat, require

ID = "leia_gaze_fix"
VERSION = 1
NAME = "蕾雅·视线固定"
DESCRIPTION = "普通或魔女蕾雅每天白天可使用一次视线固定，仅播放全场动画，无实际规则效果。"
CATEGORY = "external_default_on"
DEPENDS = ("leia",)
HANDLERS = {}


def panel_actions(game, actor, *, as_seat=None):
    from ..actions import action

    if (
        actor.get("kind") != "player"
        or game["status"] != "playing"
        or game["half"] != "day"
        or not any(item["id"] == ID for item in game["rule_plugins"])
    ):
        return []
    seat = player_seat(game, actor)
    card = current(game, seat)
    if (
        as_seat != seat["id"]
        or card is None
        or card["role_id"] != "leia"
        or not can_use_ability(game, card, bool(actor.get("puppet_controlled")))
        or game["plugin_state"].get(ID, {}).get("day") == game["day"]
    ):
        return []
    return [
        action(
            ID + ".use",
            "视线固定",
            short_label="视线固定",
            description=DESCRIPTION,
        )
    ]


def use(game, actor, events, payload, *, by_host=False):
    seat = player_seat(game, actor)
    card = current(game, seat)
    require(
        any(item["id"] == ID for item in game["rule_plugins"])
        and game["status"] == "playing"
        and game["half"] == "day"
        and card is not None
        and card["role_id"] == "leia"
        and can_use_ability(game, card, bool(actor.get("puppet_controlled")))
        and game["plugin_state"].get(ID, {}).get("day") != game["day"],
        "当前不能使用视线固定",
    )
    game["plugin_state"].setdefault(ID, {})["day"] = game["day"]
    animation = {"script": "scripts/leia-gaze-fix.json", "images": {}, "texts": {}}
    notify(
        game,
        events,
        f"{seat['id']}号发动「视线固定」。",
        alert=True,
        payload={
            "type": "skill",
            "ability": "gaze_fix",
            "ability_name": "视线固定",
            "role_id": "leia",
            "role_name": "蕾雅",
            "intro": DESCRIPTION,
            "seat_id": seat["id"],
            "actor_participant_id": seat["occupant_id"],
            "actor_name": display_player_name(seat["name"]),
            "challengeable": False,
            "target_public": False,
            "target": None,
            "_animation": {"public": animation, "owner": animation},
        },
    )


COMMANDS = {ID + ".use": use}
