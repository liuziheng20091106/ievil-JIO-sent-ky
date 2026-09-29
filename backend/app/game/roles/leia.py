ID = "leia"
VERSION = 1
LABEL = "蕾雅"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}
COMMANDS = {}


def execute_declaration(game, events, declaration, target_card):
    from ..state import notify

    cid, sid = declaration["card_id"], declaration["seat_id"]
    target = declaration["data"]["target"]
    game["cards"][cid]["uses"]["duel_day"] = game["day"]
    game["duel"] = {"day": game["day"], "leia_card": cid, "target_card": target_card["id"]}
    game["duel_approvals"] = {}
    declaration["effects"] = {"duel": cid}
    notify(
        game,
        events,
        f"{sid}号与{target}号决斗：今天所有人必须至少同意这两张牌之一，且它们达到半数即可处决。",
        alert=True,
    )
