"""Persistent JSON state and small shared rule primitives."""

from copy import deepcopy
from random import SystemRandom
from uuid import uuid4

from .catalog import NIGHT_ABILITIES, ROLES


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


def witch_faction(game):
    """开局抽定的魔女阵营：A、B 两个命运席位，A 第1天当值、B 第2天当值。

    胜负只看这两个席位是否整席出局，因此这里保存的是席位号而不是牌。
    """
    destiny = game["public"].get("witch_destiny") or {}
    return list(destiny.get("first", []))


def sherry_bound_now(game):
    """雪莉对汉娜的绑定此刻是否仍然成立；任一张牌出局即视为已经解绑。"""
    return (
        game["spiritual"]["sherry_bound"]
        and role_card(game, "sherry")["alive"]
        and role_card(game, "hanna")["alive"]
    )


def hanna_witch_window(game):
    """「汉娜魔化」开关只在第三天入夜前可调；第三天当晚的检测尚未结算时仍可补开。"""
    return game["status"] == "playing" and (
        game["day"] < 3 or (game["day"] == 3 and game["phase"] == "witch")
    )


def hanna_witch_override(game):
    """第三天夜里汉娜是否覆盖当天魔女人选。

    开关为开、汉娜在场上、汉娜曾经和雪莉绑定过、当前已经解绑、艾玛不在场，
    五条同时成立时由汉娜魔女化，顶掉魔女阵营 A、B 的补位。
    """
    return (
        bool(game.get("hanna_witch"))
        and role_card(game, "hanna")["alive"]
        and game["spiritual"]["sherry_bound"]
        and not sherry_bound_now(game)
        and not role_card(game, "emma")["alive"]
    )


def player_seat(game, actor):
    require(
        actor.get("kind") == "player" and actor.get("game_id") == game["id"], "没有玩家操作权限"
    )
    s = seat(game, actor.get("seat_id"))
    require(s["occupant_id"] == actor.get("id"), "该席位已更换操作者")
    return s


def puppet_master(game, card):
    """当前控制该傀儡牌的魔女梅露露牌；控制关系已撤销或主人已出局时返回 None。"""
    master = game["cards"].get(card["states"].get("puppet") or "")
    if master is None or not master["alive"] or not master["witch"]:
        return None
    return master


def puppet_controlled_by(game, card, seat_id):
    """该牌是否正由 seat_id 席位的魔女梅露露控制。"""
    master = puppet_master(game, card)
    if master is None:
        return False
    holder = owner(game, master["id"])
    return holder["id"] == seat_id and current(game, holder) == master


def controlled_cards(game, seat_id):
    """seat_id 当前实际控制的全部傀儡牌（仅限仍在其自己席位上的当前牌）。"""
    result = []
    for card in game["cards"].values():
        if not card["alive"] or not card["states"].get("puppet"):
            continue
        own_seat = owner(game, card["id"])
        if current(game, own_seat) != card:
            continue
        if puppet_controlled_by(game, card, seat_id):
            result.append(card)
    return result


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


def chat_event(game, events, seat_id, text, channel_id="public"):
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
        }
    )


def pending(game, kind, title, **data):
    item = {"id": uid(), "kind": kind, "title": title, "text": title, **data}
    game["pending"].append(item)
    return item


# 主持人对局日志：与玩家可见消息分离的服务端留档，只给主持人看。
# 追加统一的 {day, half, phase, kind, text} 条目，客户端按 kind 着色。
LOG_LIMIT = 400


def log_event(game, kind, text):
    entry = {
        "day": game["day"],
        "half": game["half"],
        "phase": game["phase"],
        "kind": kind,
        "text": text,
    }
    game.setdefault("log", []).append(entry)
    # 环形上限：长对局不会无限膨胀，最近 400 条足够复盘。
    if len(game["log"]) > LOG_LIMIT:
        del game["log"][: len(game["log"]) - LOG_LIMIT]


def log_index(game):
    """快照记录当时日志长度；回溯时把之后的条目裁掉，时间线与对局状态一致。"""
    return len(game.get("log", []))


def half_key(game):
    return f"{game['day']}:{game['half']}"


def living(game):
    return [s for s in game["seats"] if current(game, s)]


def lost_by_challenge(game, seat):
    """A failed challenge costs the player the game, so that seat may not challenge again."""
    return bool(seat) and seat.get("occupant_id") in game["spiritual"]["personal_losses"]


def pending_nominators(game):
    """Seats that have not nominated or passed yet; they may act at the same time.

    当前牌本阶段不能行动的席位（傀儡、下层登场受限等）拿不到提名按钮，
    也不能算作待办，否则阶段永远等不到它提交，只能由主持人纠错。
    """
    order = dict.fromkeys(
        game["public"].get("speech_order", []) + [s["id"] for s in game["seats"]]
    )
    done = game.get("nomination_done", [])
    return [
        sid
        for sid in order
        if sid not in done and (card := current(game, sid)) and card_actionable(game, card)
    ]


def eligible_voters(game):
    """有投票权的席位。

    傀儡自身无投票权，但控制它的魔女梅露露可以用该席位投票：
    控制者缺位（出局或不再是当前牌）时该席不再计票。
    """
    return [
        s
        for s in living(game)
        if (
            not (card := current(game, s))["states"].get("puppet")
            or puppet_master(game, card) is not None
        )
        and not current(game, s)["states"].get("no_vote")
        and (
            game["spiritual"]["annan_penalty"].get(current(game, s)["id"], {}).get("day")
            if isinstance(game["spiritual"]["annan_penalty"].get(current(game, s)["id"]), dict)
            else game["spiritual"]["annan_penalty"].get(current(game, s)["id"])
        )
        != game["day"]
    ]


def poison_sources(game, card):
    """返回主持人可见的动态中毒来源；玩家只看到中毒结论。"""
    sources = []
    if card["states"].get("poisoned"):
        sources.append("主持人状态")
    target_seat = next((s for s in game["seats"] if card["id"] in s["cards"]), None)
    emma = game["cards"].get("emma")
    emma_seat = next((s for s in game["seats"] if emma and emma["id"] in s["cards"]), None)
    if target_seat and emma_seat and emma["alive"]:
        indexes = {s["id"]: index for index, s in enumerate(game["seats"])}
        distance = (indexes[target_seat["id"]] - indexes[emma_seat["id"]]) % len(game["seats"])
        same_other = target_seat == emma_seat and card["id"] != emma["id"]
        adjacent_current = distance in {1, len(game["seats"]) - 1} and current(game, target_seat) == card
        if same_other or adjacent_current:
            sources.append("艾玛毒素")
    if card["role_id"] == "annan" and target_seat:
        noah = game["cards"].get("noah")
        noah_seat = next((s for s in game["seats"] if noah and noah["id"] in s["cards"]), None)
        if noah_seat and noah["alive"]:
            indexes = {s["id"]: index for index, s in enumerate(game["seats"])}
            distance = (indexes[target_seat["id"]] - indexes[noah_seat["id"]]) % len(game["seats"])
            # 同席：只有诺亚是这一席的下层牌才算来源；邻座仍按当前牌判定。
            same_seat = target_seat == noah_seat
            if (same_seat and target_seat["cards"][-1] == noah["id"]) or (
                not same_seat and distance in {1, len(game["seats"]) - 1}
            ):
                sources.append("诺亚邻接")
    return sources


def poisoned(game, card):
    return bool(poison_sources(game, card))


def effect_effective(game, events, card, ability, reveal=True):
    """掷一次中毒效果骰。

    reveal=False 用于信息类效果：本人必须收到一条结论，但不能被告知这条结论
    是真话还是假话，因此只写主持人日志，不发「中毒判定」提示。
    """
    if not poisoned(game, card):
        return True
    roll = SystemRandom().randrange(2)
    effective = roll == 0
    text = f"{ROLES[card['role_id']]['name']} · {ability}：中毒骰值{roll}，效果{'生效' if effective else '无效'}。"
    log_event(game, "poison", text)
    if reveal:
        notify(game, events, f"中毒判定：本次{ability}{'生效' if effective else '无效'}。", [owner(game, card["id"])["id"]], "中毒判定")
    return effective


def can_use_card(game, card, puppet_controlled=False):
    """当前牌是否可行动。

    傀儡牌只有控制它的魔女梅露露通过 puppet_controlled 才能代行；
    普通牌被 puppet_controlled 排除，保证一次只生成一个视角的行动。
    """
    if not card or not card["alive"] or current(game, owner(game, card["id"])) != card:
        return False
    if card["states"].get("puppet"):
        return puppet_controlled
    if puppet_controlled:
        return False
    return not card["states"].get("no_ability")


def card_actionable(game, card):
    """该当前牌现在是否可能由某位操作者行动（傀儡由其控制者代行）。"""
    if not card:
        return False
    if can_use_card(game, card):
        return True
    return can_use_card(game, card, True) and puppet_master(game, card) is not None


def seat_operable(game, seat_id):
    """该席位的当前牌是否有人操作：傀儡需要主人仍在场代行，两张牌都出局则无人。

    用于「这个席位是否还值得等」的判断。比 card_actionable 宽：不检查技能与
    no_ability，因此发言、热气球选择这类不看牌面技能的行动仍算可操作。
    """
    card = current(game, seat_id)
    if card is None:
        return False
    if card["states"].get("puppet"):
        return puppet_master(game, card) is not None
    return True


# 不允许发到同一席位的角色对：每对的两个角色牌序索引 //2 必须不同。
# 米莉亚与希罗同席时，米莉亚夜间临死换牌可能把希罗牌换走、希罗的回溯时点跟着错乱，
# 规则上不允许两人同一天挤在同一席位。
DEAL_EXCLUDED_PAIRS = (("millia", "arisa"), ("coco", "sherry"), ("millia", "hiro"))

# 艾玛、米莉亚、亚里沙不会发给同一个人，且必须放在每席两张牌的下层（牌序索引为奇数）。
DEAL_LOWER_ROLES = ("emma", "millia", "arisa")


def deal_cards(game):
    require(game["phase"] == "lobby" and not game["cards"], "本局已经发牌")
    order = list(ROLES)
    rng = SystemRandom()
    while True:
        rng.shuffle(order)
        lower_seats = {order.index(role) // 2 for role in DEAL_LOWER_ROLES}
        emma_seat = order.index("emma") // 2
        if (
            all(order.index(a) // 2 != order.index(b) // 2 for a, b in DEAL_EXCLUDED_PAIRS)
            and all(order.index(role) % 2 == 1 for role in DEAL_LOWER_ROLES)
            and len(lower_seats) == 3
            # 艾玛席另一牌不能是雪莉/亚里沙，否则前两天命运无人可转化
            and order[emma_seat * 2] not in {"sherry", "arisa"}
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
            "uses": {"bullets": 6, "shot_misses": 0} if r == "nanoka" else {},
        }
        for r in order
    }
    for i, s in enumerate(game["seats"]):
        s["cards"] = order[i * 2 : i * 2 + 2]
        s["ready"] = False
    # 开局即定本局魔女阵营：A、B 两个不同的命运席位。第1天 A 的当前牌魔女化，
    # 第2天 B 的当前牌魔女化，第3天由 A、B 中可选的一位接替。艾玛所在席位、
    # 以及另一牌是米莉亚或亚里沙的席位不能进命运，从其余席位里抽。
    emma_seat = order.index("emma") // 2
    ineligible = {
        i
        for i in range(7)
        if i == emma_seat or {order[i * 2], order[i * 2 + 1]} & {"millia", "arisa"}
    }
    eligible_seats = [i for i in range(7) if i not in ineligible]
    first = rng.sample(eligible_seats, 2) if len(eligible_seats) >= 2 else eligible_seats
    # 艾玛席第三天必定魔女化（艾玛存活时），因此对当事人也必须预告会魔女化。
    # 这里只写入逐席布尔值：客户端只读自己那一位，不再单独下发艾玛席号，
    # 否则调序阶段就会把「哪一席是艾玛」提前公开。first 是按当值顺序排列的
    # 魔女阵营 A、B 席位，胜负与第三天补位都读它。
    destiny = [i in first or i == emma_seat for i in range(7)]
    game["public"]["witch_destiny"] = {
        "seats": destiny,
        "first": [str(i + 1) for i in first],
    }
    game["phase"] = "ordering"


def upgrade_game(game):
    """就地补齐第三版规则字段；保留旧局的全部历史数据。"""
    changed = game.get("rules_revision") != 3
    game["rules_revision"] = 3

    def add(mapping, key, value):
        nonlocal changed
        if key not in mapping:
            mapping[key] = deepcopy(value)
            changed = True

    night = game.setdefault("night", {})
    for key, value in {
        "actors": {},
        "actions": [],
        "confirmed": [],
        "locked": False,
        "preview": None,
        "reactions": [],
        "extra_attacks": [],
    }.items():
        add(night, key, value)
    # 「汉娜魔化」是主持人开关，默认关闭；旧局补齐为关。
    add(game, "hanna_witch", False)
    legacy_actions = [action for action in night["actions"] if action.get("ability") not in NIGHT_ABILITIES]
    if legacy_actions:
        night.setdefault("legacy_actions", []).extend(legacy_actions)
        night["actions"] = [
            action for action in night["actions"] if action.get("ability") in NIGHT_ABILITIES
        ]
        changed = True
    spiritual = game.setdefault("spiritual", {})
    for key, value in {
        "hiro_used": {"normal": False, "witch": False},
        "hiro_exception": False,
        "sherry_bound": False,
        "annan_penalty": {},
        "personal_losses": [],
        "persistent_states": {},
    }.items():
        add(spiritual, key, value)
    public = game.setdefault("public", {})
    add(public, "declarations", [])
    add(public, "witch_destiny", None)
    for key, value in {
        "declarations": [],
        "half_exits": {},
        "photos": [],
        "marg_love": None,
        "witness": None,
        "log": [],
    }.items():
        add(game, key, value)
    for photo in game["photos"]:
        if "target" not in photo and photo.get("recipient"):
            photo["target"] = photo["recipient"]
            changed = True
        add(photo, "day", game.get("day", 1))
        add(photo, "allowed", False)
    for card in game.get("cards", {}).values():
        add(card, "states", {})
        add(card, "uses", {})
        if card.get("role_id") == "nanoka":
            add(card["uses"], "bullets", 6)
            add(card["uses"], "shot_misses", 0)
    # 第三版：13水按夜发放，一局多瓶；旧局单个持有人迁为至多一个未使用席位，
    # 旧 water.used 不再阻止之后夜晚发水，因此整局标记直接丢弃。
    water = game.get("water")
    if not isinstance(water, dict) or "holders" not in water:
        legacy = water if isinstance(water, dict) else {}
        holders = []
        if legacy.get("holder") and not legacy.get("used"):
            holders = [str(legacy["holder"])]
        game["water"] = {"holders": holders}
        changed = True
    add(game, "millia_swap", None)
    add(game, "discussion_end_requests", [])
    # 夜间死亡的下层登场、希罗选择与13水裁定改为系统自动处理，旧待办直接作废。
    stale_kinds = {"lower_entry", "hiro", "water"}
    if any(p.get("kind") in stale_kinds for p in game.get("pending", [])):
        game["pending"] = [p for p in game["pending"] if p.get("kind") not in stale_kinds]
        changed = True
    return changed


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
        "rules_revision": 3,
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
        "night": {
            "actors": {},
            "actions": [],
            "confirmed": [],
            "locked": False,
            "preview": None,
            "reactions": [],
            "extra_attacks": [],
        },
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
        "water": {"holders": []},
        "millia_swap": None,
        "discussion_end_requests": [],
        "photos": [],
        "marg_love": None,
        "declarations": [],
        "witness": None,
        "log": [],
        "surrenders": [],
        "result": None,
        "winner_candidate": None,
        "day_binding": None,
        "witch_checked_day": None,
        # 「汉娜魔化」主持人开关，默认关闭；只在第三天入夜前可改。
        "hanna_witch": False,
    }


# Only mechanical time is restored; occupant identity, public persona, and received
# information belong to real time. Seven seats make a JSON copy simpler than diffs.
# 主持人的「汉娜魔化」开关属于规则设置，不随回溯被改回，因此也不进快照。
SNAPSHOT_EXCLUDED = {
    "id",
    "version",
    "snapshots",
    "information",
    "spiritual",
    "seats",
    "hanna_witch",
}


def fallen_upper_role(game, seat):
    """席位第一张牌已经出局时的角色，用于头像上的下牌标记与悬浮回顾。"""
    if len(seat["cards"]) < 2:
        return None
    upper = game["cards"][seat["cards"][0]]
    return None if upper["alive"] else upper["role_id"]


def hiro_target_snapshot(game, half):
    """希罗的固定回溯点：夜间回到前一天顺序发言，白天回到前一天自由发言。

    找不到该时点（例如第1天夜里的死亡）时回到开局保存的最早快照。
    """
    want = "speech" if half == "night" else "discussion"
    day = game["day"] - 1
    found = next(
        (snap for snap in game["snapshots"] if snap["day"] == day and snap["phase"] == want), None
    )
    return found or (game["snapshots"][0] if game["snapshots"] else None)


def hiro_rewind(game, events, half):
    """希罗即将出局：立即按固定时点回溯一次；普通与魔女各有独立额度。

    返回 True 表示已经回溯；调用方必须停止继续写阶段与快照，否则会覆盖恢复的时间线。
    """
    hiro = role_card(game, "hiro")
    mode = "witch" if hiro["witch"] else "normal"
    if game["spiritual"]["hiro_used"][mode]:
        return False
    snap = hiro_target_snapshot(game, half)
    if snap is None:
        return False
    rewind(game, snap["id"], events, mode)
    game["rewound_night"] = True
    return True


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
        "log_index": log_index(game),
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
    # 日志是时间线的一部分：裁掉回溯点之后的条目，再记下这次回溯本身。
    if "log" in game and snap.get("log_index") is not None:
        del game["log"][snap["log_index"] :]
    log_event(game, "system", f"时间回溯到「{snap['label']}」，之后的时间线作废。")
    notify(game, events, "游戏时间已回溯；已经获得的信息与聊天记忆保留。")


def check_winner(game):
    # 好人必须在魔女阵营的两个命运席位（A、B）都整席出局时才获胜：
    # 单张魔女牌出局不算，A、B 的另一张牌仍能按第三天规则再魔女化。
    faction = witch_faction(game)
    good = bool(faction) and all(current(game, seat(game, sid)) is None for sid in faction)
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
            else "魔女阵营A、B两席出局"
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
    log_event(
        game,
        "system",
        f"对局结束：{'好人胜利' if winner == 'good' else '魔女胜利' if winner == 'witch' else '主持人结束'}（{reason}）",
    )
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
