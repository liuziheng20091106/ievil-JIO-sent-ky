"""Optional Emma treasure hunting; private rolls and protection live with the plugin."""

from random import SystemRandom

from ..state import can_use_ability, current, log_event, notify, player_seat, require, uid

ID = "emma_treasure"
VERSION = 1
NAME = "艾玛·寻宝"
DESCRIPTION = (
    "未魔女化的艾玛可在夜里寻宝：清空本席其他夜间选择，1/5概率触发地雷；"
    "提交后本夜不可修改或放弃，结果仅本人和主持人可见。"
    "安全时当天不能被魔女刀、蕾雅决斗或提名选中，全场攻击仍有效；地雷不触发米莉亚替死。"
)
CATEGORY = "external_default_off"
DEPENDS = ("emma",)
HANDLERS = {}


def is_enabled(game):
    return any(item["id"] == ID for item in game["rule_plugins"])


def panel_actions(game, actor, *, as_seat=None):
    from ..actions import action

    if actor.get("kind") != "player" or game["status"] != "playing" or game["phase"] != "night":
        return []
    seat = player_seat(game, actor)
    card = current(game, seat)
    night = game["night"]
    if (
        as_seat != seat["id"]
        or card is None
        or card["role_id"] != "emma"
        or card["witch"]
        or not can_use_ability(game, card, bool(actor.get("puppet_controlled")))
        or night["actors"].get(seat["id"]) != card["id"]
        or seat["id"] in night["confirmed"]
        or any(item["seat_id"] == seat["id"] for item in night["actions"])
    ):
        return []
    return [
        action(
            ID + ".submit",
            "选择寻宝",
            group="夜间",
            danger=True,
            short_label="寻宝",
            description=DESCRIPTION,
        )
    ]


def submit(game, actor, events, payload, *, by_host=False):
    seat = player_seat(game, actor)
    sid = seat["id"]
    card = current(game, seat)
    night = game["night"]
    require(
        is_enabled(game)
        and game["status"] == "playing"
        and game["phase"] == "night"
        and card is not None
        and card["role_id"] == "emma"
        and not card["witch"]
        and can_use_ability(game, card, bool(actor.get("puppet_controlled")))
        and night["actors"].get(sid) == card["id"]
        and sid not in night["confirmed"],
        "当前不能寻宝",
    )
    require(
        not any(
            item["ability"] == "treasure" and item["seat_id"] == sid for item in night["actions"]
        ),
        "寻宝已提交，本夜不可修改或放弃",
    )
    saved = game["plugin_state"].get(ID, {})
    if saved.get("day") == game["day"]:
        roll, mine = saved["roll"], saved["mine"]
    else:
        roll = SystemRandom().randrange(5)
        mine = roll == 0
    game["plugin_state"][ID] = {
        "day": game["day"],
        "roll": roll,
        "mine": mine,
        "card_id": card["id"],
        "protected_day": None if mine else game["day"],
    }
    night["actions"] = [item for item in night["actions"] if item["seat_id"] != sid] + [
        {
            "id": uid(),
            "seat_id": sid,
            "participant_id": actor["id"],
            "card_id": card["id"],
            "ability": "treasure",
            "confirmed": False,
            "by_host": by_host,
            "title": f"{sid}号夜间选择",
            "roll": roll,
            "mine": mine,
        }
    ]
    log_event(game, "roll", f"艾玛寻宝骰值{roll}：{'触发地雷' if mine else '安全'}。")
    notify(
        game,
        events,
        "庭院中传来一声巨响——艾玛挖到地雷了！"
        if mine
        else "你整夜在庭院里挖来挖去，然而却找到了滚木。",
        [sid],
        "寻宝结果",
    )


def treasure_protected(game, target_card_id):
    saved = game["plugin_state"].get(ID, {})
    return (
        is_enabled(game)
        and saved.get("card_id") == target_card_id
        and saved.get("protected_day") == game["day"]
    )


def night_attacks(game, action):
    if is_enabled(game) and action.get("mine"):
        return [
            {
                "target_card": action["card_id"],
                "source_card": action["card_id"],
                "cause": "treasure",
            }
        ]
    return []


COMMANDS = {ID + ".submit": submit}
