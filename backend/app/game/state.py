"""Persistent JSON state and small shared rule primitives."""

from copy import deepcopy
from random import SystemRandom
from uuid import uuid4

from .catalog import DAY_ABILITIES, NIGHT_ABILITIES, ROLES


class GameError(ValueError):
    pass


def require(condition, text="此时不能执行该操作"):
    if not condition:
        raise GameError(text)


def uid():
    return uuid4().hex


# 昵称在界面上的展示上限：存储里保留完整昵称，发往客户端的展示名一律不超过 8 个字。
PLAYER_NAME_LIMIT = 8
HOST_LABEL_PREFIX = "主持人("


def display_player_name(name, limit=PLAYER_NAME_LIMIT):
    """玩家/账号昵称的展示名：超过 8 个字截断并加省略号。

    昵称本身在存储里保持完整（账号昵称、参与身份快照、消息留档都不改写），只有
    发往界面的字符串走这里。主持人展示名是「主持人(昵称)」这种组合标签，截断时
    只动括号里的昵称，不能把「主持人(」也截掉。
    """
    text = (name or "").strip()
    if text.startswith(HOST_LABEL_PREFIX) and text.endswith(")"):
        inner = text[len(HOST_LABEL_PREFIX) : -1]
        return f"{HOST_LABEL_PREFIX}{display_player_name(inner, limit)})"
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def host_display_name(nickname):
    """对局内主持人的展示名：主持人(QQ 昵称)；昵称缺失时退回「主持人」。

    拥有主持权限的账号不止一个，只写「主持人」分不清是谁在主持，所以对局内
    一律带上昵称。
    """
    text = (nickname or "").strip()
    return f"主持人({display_player_name(text)})" if text else "主持人"


def host_label(game):
    """本局记录的主持人展示名；没记录主持人身份的旧局退回「主持人」。"""
    return host_display_name((game.get("host") or {}).get("name"))


def host_capable(actor):
    """该身份现在是否按主持人放行：主持级投影、主持管理操作与私聊可见性都看它。

    主持授权只说明「有资格主持」；进入某一局还要主持人自己确认一次（见
    ``api.host_enter``），``auth.actor_for_token`` 每次请求都在身份上标出
    ``host_entered``。未确认时这里返回 False，于是确认之前既看不到别人的上下牌，
    也拿不到主持人面板、私聊历史和任何管理操作（禁言、移人、代操作都不行）。
    手写的身份（检查与模拟器里的旧夹具）不带这个字段时按已确认处理。
    """
    return actor.get("kind") == "host" and bool(actor.get("host_entered", True))


def host_view_actor(actor):
    """生成行动表时用的身份：未确认进入的主持人按观察者处理（拿不到任何行动）。

    投影（game_view）与命令校验（engine.validate_command）共用它，避免只在一处
    收紧、另一处仍按主持人列出 host.* 与 room.* 行动。
    """
    if actor.get("kind") == "host" and not host_capable(actor):
        return {**actor, "kind": "observer"}
    return actor


def seat(game, seat_id):
    found = next((s for s in game["seats"] if s["id"] == seat_id), None)
    require(found is not None, "席位不存在")
    return found


def owner(game, card_id):
    return next(s for s in game["seats"] if card_id in s["cards"])


def seat_name(game, s):
    """席位在界面上的标识名：局内是当前展示的角色名，候场是玩家公开称呼。

    局内一律用 ``avatar_role_id``（穗乃香示人之后就是示人身份），与客户端头像上的
    角色保持一致；发牌/调序阶段不公开角色名称，因此那里仍然是玩家的公开称呼。
    """
    role_id = s.get("avatar_role_id")
    if game.get("status") != "lobby" and role_id in ROLES:
        return ROLES[role_id]["name"]
    # 候场时这里就是玩家的公开称呼：选择界面上的展示同样受 8 字上限约束。
    return display_player_name(s["name"])


def seat_label(game, s):
    """席位选项的显示文本：「座位号 · 角色名/公开称呼」。"""
    return f"{s['id']}号 · {seat_name(game, s)}"


def current(game, s):
    if isinstance(s, str):
        s = seat(game, s)
    return next((game["cards"][c] for c in s["cards"] if game["cards"][c]["alive"]), None)


def role_card(game, role):
    return next(c for c in game["cards"].values() if c["role_id"] == role)


def present(game, role):
    c = role_card(game, role)
    return c["alive"] and current(game, owner(game, c["id"])) == c


def apply_honoka_disguise(game, seat):
    """下层穗乃香登场时套用先前选定的示人角色，并就此锁定。

    返回套用的角色 id；没有选择（或她已经不是当前牌、已经锁定）时返回 None，
    由本人登场后再选一次。
    """
    card = game["cards"]["honoka"]
    if current(game, seat) != card or card["states"].get("disguise_locked"):
        return None
    role = card["states"].get("disguise")
    if not role:
        return None
    card["states"]["disguise_locked"] = True
    seat["avatar_role_id"] = role
    return role


def protection_active(game, card):
    """主持人裁定的「庇护」是否仍生效。

    庇护按天记账：第 N 天获得后，第 N 天白天/夜里与第 N+1 天白天仍然有效，
    到了第 N+1 天夜里（「第二天夜里」）自动过期。
    """
    day = card["states"].get("protected_day")
    if day is None:
        return False
    return game["day"] < day + 1 or (game["day"] == day + 1 and game["half"] == "day")


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


def notify(game, events, text, seats=None, title="游戏信息", image_id=None, alert=False, payload=None):
    recipients = None if seats is None else audience(game, seats)
    event = {
        "kind": "information" if recipients is not None else ("alert" if alert else "notice"),
        "text": text,
        "audience": recipients,
        "title": title,
    }
    if image_id:
        event["image_id"] = image_id
    if payload is not None:
        # 结构化载荷里带的是「谁能看到多少」的完整真相，投影在 storage.message_view 里做。
        event["payload"] = payload
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


def debunked_abilities(game, seat_id):
    """被质疑拆穿的技能：该席位本局不能再发动同一技能。

    「质疑成功」是声明状态 stopped 的唯一来源，因此直接从声明记录派生，
    不需要单独记账；回溯时随声明记录一起还原时间线。
    """
    return {
        declaration["ability"]
        for declaration in game.get("declarations", [])
        if declaration["seat_id"] == seat_id and declaration["status"] == "stopped"
    }


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


def annan_penalty_day(game, seat_id):
    """该席位当天的安安后果日；旧局按牌记账的整数或字典都能读。"""
    penalty = game["spiritual"]["annan_penalty"].get(seat_id)
    if isinstance(penalty, dict):
        return penalty.get("day")
    return penalty


def eligible_voters(game):
    """有投票权的席位。

    傀儡自身无投票权，但控制它的魔女梅露露可以用该席位投票：
    控制者缺位（出局或不再是当前牌）时该席不再计票。
    安安后果按席位记账，因此该席换当前牌也不会洗掉「次日失去投票权」。
    """
    return [
        s
        for s in living(game)
        if (
            not (card := current(game, s))["states"].get("puppet")
            or puppet_master(game, card) is not None
        )
        and not current(game, s)["states"].get("no_vote")
        and annan_penalty_day(game, s["id"]) != game["day"]
    ]


def active_duel(game):
    """当天仍然有效的蕾雅决斗。

    决斗只在宣布当天有效。投票开始时由 open_vote 打上 locked：轮次表一旦排定就
    不再随出局变化，否则中途有人出局会让最后一轮索引错位；真正出局的牌由预结算
    按「已不在场」跳过。还没开始投票时，有一张先出局则整场决斗失效，不会留下
    投不动的候选。
    """
    duel = game.get("duel")
    if not duel or duel["day"] != game["day"]:
        return None
    if duel.get("locked"):
        return duel
    if not all(game["cards"][cid]["alive"] for cid in (duel["leia_card"], duel["target_card"])):
        return None
    return duel


def duel_cards(game):
    """当天决斗的两张牌，蕾雅在前、决斗对象在后。"""
    duel = active_duel(game)
    return [duel["leia_card"], duel["target_card"]] if duel else []


def duel_vote_exempt(game, card, duel):
    """决斗强制投票的豁免。

    雪莉不能同意处决绑定的汉娜，这条优先级高于「必须至少投一个」：
    汉娜是决斗对象时雪莉可以整轮弃票。
    """
    return card["id"] == "sherry" and game["spiritual"]["sherry_bound"] and "hanna" in duel


def duel_vote_required(game, seat_id):
    """该席位是否还欠决斗的一张同意票。

    决斗当天所有人必须至少同意两张决斗牌之一：投出任意一张决斗同意票后
    ``duel_approvals`` 置位，这条要求就消失。雪莉对汉娜的限制优先豁免，
    所以那种情况不会强制。
    """
    if game["phase"] != "voting":
        return False
    duel = duel_cards(game)
    if len(duel) < 2 or game["duel_approvals"].get(seat_id):
        return False
    card = current(game, seat_id)
    if card is None:
        return False
    return not duel_vote_exempt(game, card, duel)


def nomination_rounds(game):
    """今天要投的候选，先提名者排在前面。

    同一张牌被多人提名只投一轮；蕾雅决斗当天的两张牌直接排在最前面，
    不需要任何人提名。
    """
    rounds, seen = [], set()
    for cid in duel_cards(game):
        seen.add(cid)
        rounds.append({"seat_id": owner(game, cid)["id"], "card_id": cid, "by": None})
    for item in game["nominations"]:
        if item["card_id"] in seen:
            continue
        seen.add(item["card_id"])
        rounds.append(item)
    return rounds


def nomination_auto_yes(game, seat_id, card_id):
    """该席位是否因提名过这张牌而自动投同意票。

    「提名过该候选自动同意」优先于玩家的选择；但绑定中的雪莉不能同意处决汉娜，
    那条限制又优先于自动同意，因此她这一次提名不产生同意票。
    """
    if not any(n["by"] == seat_id and n["card_id"] == card_id for n in game["nominations"]):
        return False
    if card_id == "hanna" and game["spiritual"]["sherry_bound"]:
        card = current(game, seat_id)
        if card is not None and card["id"] == "sherry":
            return False
    return True


def seat_choice(game, seat_id, card_id):
    """该席位对某个候选的选择；还没投且没有自动同意票时返回 None。

    自动同意票不写进 ``game["ballots"]``：它是提名推导出来的结论，玩家自己没有
    提交过，因此这里按规则实时算。
    """
    if nomination_auto_yes(game, seat_id, card_id):
        return "yes"
    return ((game.get("ballots") or {}).get(seat_id) or {}).get(card_id)


def ballot_selection(game, seat_id):
    """该席位对今天全部候选的选择（省略尚未选择的候选），用于投影与日志。"""
    return {
        item["card_id"]: choice
        for item in nomination_rounds(game)
        if (choice := seat_choice(game, seat_id, item["card_id"]))
    }


def ballot_complete(game, seat_id):
    """该席位是否已经对今天全部候选做出选择；今天没有候选时视为完成。"""
    return all(
        seat_choice(game, seat_id, item["card_id"]) is not None
        for item in nomination_rounds(game)
    )


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


def effect_effective(game, card, ability):
    """掷一次中毒效果骰。

    中毒对玩家完全隐藏：只写主持人日志，不向本人发「中毒判定」，本人拿到的
    信息真假由这次掷骰决定。
    """
    if not poisoned(game, card):
        return True
    roll = SystemRandom().randrange(2)
    effective = roll == 0
    text = f"{ROLES[card['role_id']]['name']} · {ability}：中毒骰值{roll}，效果{'生效' if effective else '无效'}。"
    log_event(game, "poison", text)
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


def seat_eliminated(game, seat_or_id):
    """该席位现在是否已整席出局：对局进行中且两张牌都不在场。

    候场与调序阶段还没发牌，每个席位都没有当前牌，那不是出局；对局结束后
    限制也不再适用。出局不是永久标签：希罗回溯、梅露露复活与主持人回溯都会
    让角色牌重新登场，所以一律按当前牌现场判断，不做单独记账。
    """
    if game["status"] != "playing":
        return False
    return current(game, seat_or_id) is None


def participant_eliminated(game, participant_id):
    """该参与者现在是否已整席出局；找不到席位（已替补离场等）按不在局处理。"""
    if not participant_id or participant_id == "host":
        return False
    found = next((s for s in game["seats"] if s["occupant_id"] == participant_id), None)
    return found is not None and seat_eliminated(game, found)


def actor_eliminated(game, actor):
    """当前操作者是否已整席出局；主持人、观战者与未入座身份恒为 False。"""
    if actor.get("kind") != "player":
        return False
    return participant_eliminated(game, actor.get("id"))


def seat_operable(game, seat_id):
    """该席位的当前牌是否有人操作：傀儡需要主人仍在场代行，两张牌都出局则无人。

    用于「这个席位是否还值得等」的判断。比 card_actionable 宽：不检查技能与
    no_ability，因此发言这类不看牌面技能的行动仍算可操作。
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
    """就地补齐第六版规则字段；保留旧局的全部历史数据。"""
    changed = game.get("rules_revision") != 6
    game["rules_revision"] = 6

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
    # 主持人身份快照与「已确认进入管理界面」的主持账号：旧局补齐为「没有记录」。
    add(game, "host", None)
    add(game, "host_entries", [])
    # 旧字段名只是同一份记录的前身（当时只用来给通告去重），合并后丢掉。
    legacy_entries = game.pop("host_entry_notices", None)
    if legacy_entries:
        game["host_entries"] = list(dict.fromkeys([*game["host_entries"], *legacy_entries]))
        changed = True
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
        # 第四版：蕾雅白天决斗当天的投票状态；旧局补齐为「今天没有决斗」。
        "duel": None,
        "duel_approvals": {},
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
    # 热气球玩法已整体移除：停在热气球阶段的旧局直接改判为提名，并清掉该玩法的
    # 全部状态，否则旧阶段名与旧技能会在 PHASES／DAY_ABILITIES 里查表失败。
    if game.get("phase") == "balloon":
        game["phase"] = "nomination"
        changed = True
    for key in ("balloon_choices", "balloon_proposal"):
        if key in game:
            game.pop(key)
            changed = True
    if "balloon" in public:
        public.pop("balloon")
        changed = True
    legacy_balloons = [
        declaration
        for declaration in game.get("declarations", [])
        if declaration.get("ability") not in DAY_ABILITIES
    ]
    if legacy_balloons:
        game.setdefault("legacy_declarations", []).extend(legacy_balloons)
        dropped = {declaration["id"] for declaration in legacy_balloons}
        game["declarations"] = [
            declaration for declaration in game["declarations"] if declaration["id"] not in dropped
        ]
        public["declarations"] = [
            item for item in public.get("declarations", []) if item.get("id") not in dropped
        ]
        changed = True
    # 夜间死亡的下层登场、希罗选择与13水裁定改为系统自动处理，旧待办直接作废。
    stale_kinds = {"lower_entry", "hiro", "water"}
    if any(p.get("kind") in stale_kinds for p in game.get("pending", [])):
        game["pending"] = [p for p in game["pending"] if p.get("kind") not in stale_kinds]
        changed = True
    # 第五版：庇护改为按天记账（第 N 天获得，第 N+1 天夜里过期），旧的布尔状态按当前日补日戳；
    # 安安后果由按牌记账迁移为按席位记账，换当前牌不再洗掉处罚。
    for card in game.get("cards", {}).values():
        states = card.setdefault("states", {})
        if states.pop("protected", None):
            states.setdefault("protected_day", game.get("day", 1))
            changed = True
    seat_ids = {s["id"] for s in game.get("seats", [])}
    penalty = spiritual.get("annan_penalty") or {}
    if any(key not in seat_ids for key in penalty):
        migrated = {}
        for key, value in penalty.items():
            seat_id = owner(game, key)["id"] if key in game.get("cards", {}) else key
            if seat_id in seat_ids:
                migrated.setdefault(seat_id, value)
        spiritual["annan_penalty"] = migrated
        changed = True
    for states in (spiritual.get("persistent_states") or {}).values():
        if states.pop("protected", None):
            states.setdefault("protected_day", game.get("day", 1))
            changed = True
    # 第六版：投票改为一次性提交全部候选，计票表 votes 换成 ballots。
    # 正停在投票阶段的旧局要把已经投出的当前轮选票搬过去，否则当事人得重投一轮。
    legacy_votes = game.pop("votes", None)
    add(game, "ballots", {})
    if game.get("phase") == "voting" and legacy_votes:
        rounds = nomination_rounds(game)
        index = len(game.get("vote_rounds", []))
        if index < len(rounds):
            card_id = rounds[index]["card_id"]
            for seat_id, choice in legacy_votes.items():
                if choice:
                    game["ballots"].setdefault(seat_id, {}).setdefault(card_id, choice)
    if legacy_votes is not None:
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
        "rules_revision": 6,
        # 建立这一局的主持人身份快照：对局内显示「主持人(昵称)」，
        # 也让非本局主持人进入管理界面时能被认出来（见 api.host_enter）。
        "host": None,
        # 已经确认进入本局管理界面的主持账号；未确认前不下发主持级数据，
        # 也是「非建局主持人进入」通告的去重依据（见 api.host_enter）。
        "host_entries": [],
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
            "votes": {},
            "declarations": [],
            "rewinds": 0,
        },
        "nominations": [],
        "speech_passed": [],
        "speech_queued": {},
        "queued_notices": [],
        "queued_reveals": [],
        # 今天的选票：{席位: {角色牌: 同意/不同意/弃票}}。提名自动同意票不写进来，
        # 由 state.seat_choice 按规则实时推导；计票表（旧字段 votes）已删除。
        "ballots": {},
        "vote_rounds": [],
        "execution": [],
        "execution_ready": [],
        "water": {"holders": []},
        "millia_swap": None,
        "discussion_end_requests": [],
        "photos": [],
        "marg_love": None,
        # 蕾雅当天宣布的决斗：{day, leia_card, target_card}；当天投票用它强制候选与半数门槛。
        "duel": None,
        "duel_approvals": {},
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


def finish(game, events, winner, reason):
    losses = list(game["spiritual"]["personal_losses"])
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


def clear_seat_actions(game, seat_id, events=None):
    require(any(s["id"] == seat_id for s in game["seats"]), "席位不存在")
    night = game["night"]
    night["actions"] = [a for a in night["actions"] if a["seat_id"] != seat_id]
    night["confirmed"] = [s for s in night["confirmed"] if s != seat_id]
    # 米莉亚清除本夜选择时，正在生效的换血目标也一并作废，避免留下没有行动记录的替死。
    if game.get("millia_swap") and owner(game, "millia")["id"] == seat_id:
        game["millia_swap"] = None
    if night.get("locked") and game["phase"] == "night_review":
        from .resolution import prepare_night_preview

        game["pending"] = [
            p for p in game["pending"] if p["kind"] != "hiro" or p.get("preview")
        ]
        night["reactions"] = []
        # 重算预结算同样可能触发希罗回溯，事件队列要一起传下去（见 prepare_night_preview）。
        prepare_night_preview(game, events)
    game["warnings"].pop(seat_id, None)
    game["deadline"] = min(game["warnings"].values(), default=None)
