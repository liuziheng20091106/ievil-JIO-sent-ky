ID = "coco"
VERSION = 1
LABEL = "可可"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}
COMMANDS = {}


def coco_seat(game):
    from ..state import owner, role_card

    card = role_card(game, ID)
    sid = owner(game, card["id"])["id"]
    return sid if card["witch"] and game["night"]["actors"].get(sid) == card["id"] else None


def witch_information(game, events):
    from ..catalog import ROLES
    from ..resolution import information
    from ..state import present, role_card, witch_faction

    if present(game, ID) and role_card(game, ID)["witch"]:
        codex = game["codex"]
        information(
            game,
            events,
            role_card(game, ID),
            "魔女可可线索",
            "魔典顺序：" + "、".join(ROLES[r]["name"] for r in codex),
            "魔典顺序：" + "、".join(ROLES[r]["name"] for r in codex[-1:] + codex[:-1]),
        )
        faction = set(witch_faction(game))
        seats = game["seats"]
        truth = [s["id"] in faction for s in seats]
        false = truth[-1:] + truth[:-1]
        information(
            game,
            events,
            role_card(game, ID),
            "全员阵营",
            "\n".join(
                f"{s['id']}号：{'魔女阵营' if evil else '好人阵营'}"
                for s, evil in zip(seats, truth, strict=True)
            ),
            "\n".join(
                f"{s['id']}号：{'魔女阵营' if evil else '好人阵营'}"
                for s, evil in zip(seats, false, strict=True)
            ),
        )


def unlock_coco(game, events):
    from .. import plugins
    from ..resolution import information, night_text
    from ..state import role_card, start_phase

    cs = coco_seat(game)
    others = set(game["night"]["actors"]) - ({cs} if cs else set())
    if cs and others.issubset(game["night"]["confirmed"]) and game["phase"] == "night":
        start_phase(game, "night_coco")
        information(
            game,
            events,
            role_card(game, ID),
            "其余夜间行动已锁定",
            night_text(game, game["night"]["actions"]),
            "中毒幻觉：未辨识到有效夜间行动",
        )
        plugins.emit(
            game, events, "phase_enter", {"from": "night", "to": "night_coco", "day": game["day"]}
        )


def execute_declaration(game, events, declaration, target_card):
    from ..state import notify, uid

    sid, target = declaration["seat_id"], declaration["data"]["target"]
    game["photos"].append(
        {"id": uid(), "sender": sid, "target": target, "day": game["day"], "allowed": False}
    )
    notify(game, events, "收到照片，可自愿授权发送者查看你的夜间行动。", [target], "收到照片")
