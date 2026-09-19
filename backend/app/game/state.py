"""Persistent JSON state and small shared rule primitives."""

from copy import deepcopy
from random import SystemRandom
from uuid import uuid4

from .catalog import ROLES


class GameError(ValueError):
    pass


def require(condition, text="此时不能执行该操作"):
    if not condition:
        raise GameError(text)


def uid():
    return uuid4().hex


def seat(game, seat_id):
    found = next((s for s in game["seats"] if s["id"] == seat_id), None)
    require(found is not None, "席位不存在")
    return found


def owner(game, card_id):
    return next(s for s in game["seats"] if card_id in s["cards"])


def current(game, s):
    if isinstance(s, str):
        s = seat(game, s)
    return next((game["cards"][c] for c in s["cards"] if game["cards"][c]["alive"]), None)


def role_card(game, role):
    return next(c for c in game["cards"].values() if c["role_id"] == role)


def present(game, role):
    c = role_card(game, role)
    return c["alive"] and current(game, owner(game, c["id"])) == c


def player_seat(game, actor):
    require(
        actor.get("kind") == "player" and actor.get("game_id") == game["id"], "没有玩家操作权限"
    )
    s = seat(game, actor.get("seat_id"))
    require(s["occupant_id"] == actor.get("id"), "该席位已更换操作者")
    return s


def audience(game, seats):
    return [s["occupant_id"] for s in game["seats"] if s["id"] in seats and s["occupant_id"]]


def notify(game, events, text, seats=None, title="游戏信息", image_id=None, alert=False):
    recipients = None if seats is None else audience(game, seats)
    event = {
        "kind": "information" if recipients is not None else ("alert" if alert else "notice"),
        "text": text,
        "audience": recipients,
        "title": title,
    }
    if image_id:
        event["image_id"] = image_id
    events.append(event)
    if recipients is not None or image_id:
        game["information"].append({"id": uid(), **deepcopy(event)})


def chat_event(game, events, seat_id, text, channel_id="public", mimic_seat_id=None):
    """公开发言以玩家消息发布，两端展示与玩家自己发送的普通发言完全一致。"""
    s = seat(game, seat_id)
    events.append(
        {
            "kind": "chat",
            "channel_id": channel_id,
            "text": text,
            "audience": None,
            "sender_id": s["occupant_id"],
            "sender_name": s["name"],
            "avatar_role_id": s["avatar_role_id"],
            "mimic_seat_id": mimic_seat_id,
        }
    )


def pending(game, kind, title, **data):
    item = {"id": uid(), "kind": kind, "title": title, "text": title, **data}
    game["pending"].append(item)
    return item


def half_key(game):
    return f"{game['day']}:{game['half']}"


def living(game):
    return [s for s in game["seats"] if current(game, s)]


def lost_by_challenge(game, seat):
    """A failed challenge costs the player the game, so that seat may not challenge again."""
    return bool(seat) and seat.get("occupant_id") in game["spiritual"]["personal_losses"]


def pending_nominators(game):
    """Seats that have not nominated or passed yet; they may act at the same time."""
    order = dict.fromkeys(
        game["public"].get("speech_order", []) + [s["id"] for s in game["seats"]]
    )
    done = game.get("nomination_done", [])
    return [sid for sid in order if sid not in done and current(game, sid)]


def eligible_voters(game):
    return [
        s
        for s in living(game)
        if not current(game, s)["states"].get("puppet")
        and not current(game, s)["states"].get("no_vote")
        and game["spiritual"]["annan_penalty"].get(current(game, s)["id"]) != game["day"]
    ]


def poisoned(card):
    return bool(card["states"].get("poisoned"))


def can_use_card(game, card):
    if not card or not card["alive"] or current(game, owner(game, card["id"])) != card:
        return False
    if card["states"].get("entry_blocked_at") == f"{game['day']}:{game['phase']}":
        return False
    return not any(
        p["kind"] == "lower_entry" and p["card_id"] == card["id"] for p in game["pending"]
    )


# 不允许发到同一席位的角色对：每对的两个角色牌序索引 //2 必须不同。
DEAL_EXCLUDED_PAIRS = (("millia", "arisa"), ("coco", "sherry"))


def deal_cards(game):
    require(game["phase"] == "lobby" and not game["cards"], "本局已经发牌")
    order = list(ROLES)
    rng = SystemRandom()
    while True:
        rng.shuffle(order)
        if all(
            order.index(a) // 2 != order.index(b) // 2 for a, b in DEAL_EXCLUDED_PAIRS
        ):
            break
    game["cards"] = {
        r: {
            "id": r,
            "role_id": r,
            "original_role_id": r,
            "alive": True,
            "witch": False,
            "injured": False,
            "states": {},
            "uses": {"bullets": 6} if r == "nanoka" else {},
        }
        for r in order
    }
    for i, s in enumerate(game["seats"]):
        s["cards"] = order[i * 2 : i * 2 + 2]
        s["ready"] = False
    game["phase"] = "ordering"


def create_game(codex):
    require(
        isinstance(codex, list)
        and len(codex) == 11
        and all(isinstance(r, str) and r in ROLES for r in codex)
        and len(set(codex)) == 11,
        "请确认11名不重复的魔典角色",
    )
    shuffled_codex = list(codex)
    SystemRandom().shuffle(shuffled_codex)
    return {
        "id": uid(),
        "version": 0,
        "status": "lobby",
        "join_open": False,
        "day": 1,
        "half": "night",
        "phase": "lobby",
        "deadline": None,
        "codex": shuffled_codex,
        "cards": {},
        "seats": [
            {
                "id": str(i + 1),
                "occupant_id": None,
                "name": f"{i + 1}号玩家",
                "avatar_role_id": None,
                "ready": False,
                "cards": [],
            }
            for i in range(7)
        ],
        "information": [],
        "pending": [],
        "snapshots": [],
        "night": {"actors": {}, "actions": [], "confirmed": [], "locked": False, "preview": None},
        "warnings": {},
        "deaths": [],
        "half_exits": {},
        "generated_witches": [],
        "spiritual": {
            "hiro_used": {"normal": False, "witch": False},
            "hiro_exception": False,
            "sherry_bound": False,
            "annan_penalty": {},
            "personal_losses": [],
            "persistent_states": {},
        },
        "public": {
            "speaker": None,
            "speech_order": [],
            "balloon": {"progress": 0, "participants": [], "day": 0, "status": "idle"},
            "votes": {},
            "declarations": [],
            "achievements_enabled": True,
            "rewinds": 0,
        },
        "balloon_choices": {},
        "balloon_proposal": None,
        "nominations": [],
        "speech_passed": [],
        "speech_queued": {},
        "queued_notices": [],
        "queued_reveals": [],
        "votes": {},
        "vote_rounds": [],
        "brainwash": {},
        "execution": [],
        "execution_ready": [],
        "water": {"holder": None, "used": False},
        "photos": [],
        "gaze": None,
        "declarations": [],
        "surrenders": [],
        "result": None,
        "winner_candidate": None,
        "day_binding": None,
        "witch_checked_day": None,
    }


# Only mechanical time is restored; occupant identity, public persona, and received
# information belong to real time. Seven seats make a JSON copy simpler than diffs.
SNAPSHOT_EXCLUDED = {"id", "version", "snapshots", "information", "spiritual", "seats"}


def fallen_upper_role(game, seat):
    """席位第一张牌已经出局时的角色，用于头像上的下牌标记与悬浮回顾。"""
    if len(seat["cards"]) < 2:
        return None
    upper = game["cards"][seat["cards"][0]]
    return None if upper["alive"] else upper["role_id"]


def hiro_pending(game, events, mode, preview=None, phase=None):
    """希罗即将出局：选择权交回本人，主持人只处理前一天同一时点之外的裁定。"""
    sid = owner(game, "hiro")["id"]
    pending(
        game,
        "hiro",
        "希罗即将出局：等待本人选择回溯或继续",
        mode=mode,
        seat_id=sid,
        expected_day=game["day"] - 1,
        expected_phase=game["phase"] if phase is None else phase,
        preview=preview,
    )
    notify(
        game,
        events,
        "你庇护后仍会出局：可以回溯到前一天同一时点，或在行动面板选择按预结算继续。",
        [sid],
        "希罗回溯",
    )


def hiro_dilemma(game, seat_id):
    """希罗即将出局时挂起的回溯选择；由本人作答，主持人只在特殊时点介入。"""
    return next(
        (p for p in game["pending"] if p["kind"] == "hiro" and p.get("seat_id") == seat_id), None
    )


def snapshot_for(game, item):
    """希罗的合法回溯点：前一天的同一时点。其他时点仍由主持人裁定。"""
    return next(
        (
            snap
            for snap in game["snapshots"]
            if snap["day"] == item["expected_day"] and snap["phase"] == item["expected_phase"]
        ),
        None,
    )


def save_snapshot(game):
    label = f"第{game['day']}天 · {game['phase']}"
    state = {k: deepcopy(v) for k, v in game.items() if k not in SNAPSHOT_EXCLUDED}
    state["seat_cards"] = {s["id"]: list(s["cards"]) for s in game["seats"]}
    snap = {
        "id": uid(),
        "day": game["day"],
        "half": game["half"],
        "phase": game["phase"],
        "label": label,
        "state": state,
    }
    game["snapshots"].append(snap)
    return snap


def rewind(game, snapshot_id, events, mode=None, keep_states=()):
    snap = next((s for s in game["snapshots"] if s["id"] == snapshot_id), None)
    require(snap is not None, "回溯时间点不存在")
    if mode:
        require(not game["spiritual"]["hiro_used"][mode], "该身份的回溯额度已用尽")
        game["spiritual"]["hiro_used"][mode] = True
    retained = {
        cid: deepcopy(game["cards"][cid]["states"]) for cid in keep_states if cid in game["cards"]
    }
    spiritual = game["spiritual"]
    mechanical = deepcopy(snap["state"])
    cards_by_seat = mechanical.pop("seat_cards")
    for key in tuple(game):
        if key not in SNAPSHOT_EXCLUDED:
            del game[key]
    game.update(mechanical)
    for s in game["seats"]:
        s["cards"] = cards_by_seat[s["id"]]
    game["spiritual"] = spiritual
    for cid, states in spiritual["persistent_states"].items():
        game["cards"][cid]["states"].update(states)
    for cid, states in retained.items():
        game["cards"][cid]["states"].update(states)
    if mode == "witch":
        role_card(game, "hiro")["witch"] = True
        if "hiro" not in game["generated_witches"]:
            game["generated_witches"].append("hiro")
    game["warnings"] = {}
    game["deadline"] = None
    game["public"]["rewinds"] += 1
    notify(game, events, "游戏时间已回溯；已经获得的信息与聊天记忆保留。")


def move_hanna(game, offset):
    if "hanna" in game["codex"]:
        old = game["codex"].index("hanna")
        game["codex"].pop(old)
        game["codex"].insert(max(0, min(len(game["codex"]), old + offset)), "hanna")


def check_winner(game):
    active_witches = [c for c in game["cards"].values() if c["alive"] and c["witch"]]
    good = bool(game["generated_witches"]) and not active_witches
    evil = not role_card(game, "millia")["alive"] and not role_card(game, "arisa")["alive"]
    winner = (
        ("good" if game["half"] == "day" else "witch")
        if good and evil
        else "good"
        if good
        else "witch"
        if evil
        else None
    )
    game["winner_candidate"] = (
        {
            "winner": winner,
            "reason": "双方同一半天达成条件，白天好人优先、夜晚魔女优先"
            if good and evil
            else "所有已生成魔女出局"
            if good
            else "米莉亚与亚里沙均出局",
        }
        if winner
        else None
    )


def finish(game, events, winner, reason, balloon=False):
    losses = list(game["spiritual"]["personal_losses"])
    if balloon:
        losses.extend(audience(game, [owner(game, "annan")["id"]]))
    personal = []
    if game["spiritual"]["sherry_bound"]:
        hanna_side = "witch" if role_card(game, "hanna")["witch"] else "good"
        personal.append(
            {
                "seat_id": owner(game, "sherry")["id"],
                "label": "雪莉胜负跟随汉娜",
                "won": winner == hanna_side,
            }
        )
    game["result"] = {
        "winner": winner,
        "reason": reason,
        "personal_losses": list(dict.fromkeys(losses)),
        "personal_results": personal,
    }
    game["status"] = "ended"
    game["deadline"] = None
    game["warnings"] = {}
    game["queued_reveals"] = []
    notify(
        game,
        events,
        f"对局结束：{'好人' if winner == 'good' else '魔女' if winner == 'witch' else '主持人结束'}。{reason}",
    )


def clear_seat_actions(game, seat_id):
    require(any(s["id"] == seat_id for s in game["seats"]), "席位不存在")
    night = game["night"]
    night["actions"] = [a for a in night["actions"] if a["seat_id"] != seat_id]
    night["confirmed"] = [s for s in night["confirmed"] if s != seat_id]
    if night.get("locked") and game["phase"] == "night_review":
        from .resolution import prepare_night_preview

        game["pending"] = [
            p for p in game["pending"] if p["kind"] != "hiro" or p.get("preview")
        ]
        night["reactions"] = []
        prepare_night_preview(game)
    game["warnings"].pop(seat_id, None)
    game["deadline"] = min(game["warnings"].values(), default=None)
