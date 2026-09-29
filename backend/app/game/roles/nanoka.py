from random import SystemRandom

ID = "nanoka"
VERSION = 1
LABEL = "奈乃香"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}
COMMANDS = {}


def scan_witches(game, events, card):
    from ..catalog import ROLES
    from ..resolution import information

    cards = list(game["cards"].values())
    information(
        game,
        events,
        card,
        "全员魔女化状态",
        "；".join(
            f"{ROLES[c['role_id']]['name']}：{'魔女' if c['witch'] else '普通'}" for c in cards
        ),
        "；".join(
            f"{ROLES[c['role_id']]['name']}：{'普通' if c['witch'] else '魔女'}" for c in cards
        ),
    )


def auto_gaze(game, events):
    """Resolve the passive when the execution list is finalized, even for a puppet."""
    from ..resolution import information
    from ..state import passive_card_payload, present

    card = game["cards"].get(ID)
    if not card or card["uses"].get("gaze_day") == game["day"] or not present(game, ID):
        return
    card["uses"]["gaze_day"] = game["day"]
    truth = any(game["cards"][cid]["witch"] for cid in game["execution"])
    information(
        game,
        events,
        card,
        "处决幻视",
        f"本日处决名单{'含有' if truth else '不含'}魔女。",
        f"本日处决名单{'不含' if truth else '含有'}魔女。",
        payload=passive_card_payload(game, "gaze", ""),
    )


def shoot(game, actor, events, payload, *, by_host=False):

    from ..state import GameError, can_use_ability, current, log_event, notify, player_seat, require

    sid = player_seat(game, actor)["id"]
    card = current(game, sid)
    if card is None:
        raise GameError("奈乃香当前没有登场角色牌")
    require(
        by_host or can_use_ability(game, card, bool(actor.get("puppet_controlled"))),
        "傀儡与失去技能的角色不能发动技能",
    )
    require(card["uses"].get("bullets", 0) > 0, "子弹已经用完")
    card["uses"]["bullets"] -= 1
    threshold = min(card["uses"].get("shot_misses", 0) + 1, 6)
    roll = SystemRandom().randrange(6) + 1
    target = current(game, payload["target"])
    if target is None:
        raise GameError("目标当前没有登场角色牌")
    hit = roll <= threshold
    card["uses"]["shot_misses"] = 0 if hit else min(threshold, 6)
    game.setdefault("execution_rolls", []).append(
        {
            "day": game["day"],
            "roll": roll,
            "threshold": threshold,
            "target_card": target["id"],
            "effective": True,
            "hit": hit,
        }
    )
    log_event(
        game,
        "roll",
        f"奈乃香临刑开枪：命中阈值{threshold}/6，骰值{roll}，{'命中' if hit else '未命中'}。",
    )
    if hit:
        game.setdefault("execution_shots", []).append(
            {"target_card": target["id"], "source_card": card["id"], "cause": "shoot"}
        )
    bullets = card["uses"]["bullets"]
    if bullets <= 0:
        game["execution_ready"].append(sid)
    notify(
        game,
        events,
        f"{sid}号临刑开枪，命中率{threshold}/6，{'命中' if hit else '未命中'}；剩余{bullets}颗子弹。",
        alert=True,
    )
