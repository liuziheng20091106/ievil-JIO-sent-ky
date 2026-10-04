"""希罗每日一次发布伪造的全场系统消息。"""

from ..animations import skill_animation_snapshot
from ..state import can_use_ability, current, notify, player_seat, require

ID = "hiro_forgery"
VERSION = 2
NAME = "希罗·伪证"
DESCRIPTION = (
    "希罗每天可发布一次自定义全场系统消息，可选择加入公开证物；技能提示只对本人和主持人可见。"
)
CATEGORY = "external_default_on"
DEPENDS = ("hiro",)
HANDLERS = {}


def panel_actions(game, actor, *, as_seat=None):
    from ..actions import action, field

    if actor.get("kind") != "player" or game["status"] != "playing":
        return []
    seat = player_seat(game, actor)
    card = current(game, seat)
    if (
        as_seat != seat["id"]
        or card is None
        or card["role_id"] != "hiro"
        or game["plugin_state"].get(ID, {}).get("day") == game["day"]
    ):
        return []
    return [
        action(
            ID + ".publish",
            "发布伪证",
            [
                field("text", "系统消息内容", "textarea"),
                field("evidence", "加入证物", "checkbox", required=False),
            ],
            group="行动",
            short_label="伪证",
        )
    ]


def publish(game, actor, events, payload, *, by_host=False):
    seat = player_seat(game, actor)
    card = current(game, seat)
    require(
        game["status"] == "playing"
        and card is not None
        and card["role_id"] == "hiro"
        and can_use_ability(game, card, bool(actor.get("puppet_controlled")))
        and game["plugin_state"].get(ID, {}).get("day") != game["day"],
        "当前不能使用伪证",
    )
    text = payload["text"].strip()
    require(bool(text), "系统消息不能为空")
    game["plugin_state"].setdefault(ID, {})["day"] = game["day"]
    notify(
        game,
        events,
        "你已使用伪证。",
        [seat["id"]],
        "伪证",
        payload={
            "type": "animation",
            "actor_participant_id": seat["occupant_id"],
            "_animation": skill_animation_snapshot("hiro", "forgery", "伪证", card["witch"]),
        },
    )
    notify(
        game,
        events,
        text,
        reference_title="系统公告" if payload.get("evidence") else None,
    )


COMMANDS = {ID + ".publish": publish}
