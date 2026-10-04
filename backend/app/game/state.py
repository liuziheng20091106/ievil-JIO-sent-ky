"""Persistent JSON state and small shared rule primitives."""

import unicodedata
from copy import deepcopy
from random import SystemRandom
from uuid import uuid4

from .animations import skill_animation_snapshot
from . import clock
from .catalog import DAY_ABILITIES, NIGHT_ABILITIES, ROLES
from .roles import emma


class GameError(ValueError):
    pass


def require(condition, text="此时不能执行该操作"):
    if not condition:
        raise GameError(text)


def uid():
    return uuid4().hex


def start_phase(game, phase):
    """记录真正进入阶段的时间；同阶段回溯也重新从此刻开始。"""
    game["phase"] = phase
    game["public"]["phase_started_at"] = clock.now()


# 昵称在界面上的展示上限：存储里保留完整昵称，发往客户端的展示名一律不超过 16 个
# 半角宽度——中文等全角字符按 2 个算，字母数字按 1 个算（8 个汉字正好占满）。
PLAYER_NAME_LIMIT = 16
HOST_LABEL_PREFIX = "主持人("


def _name_width(char):
    """单个字符的展示宽度：全角（中日韩、全角标点等）按 2，其余按 1。"""
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def display_player_name(name, limit=PLAYER_NAME_LIMIT):
    """玩家/账号昵称的展示名：超过 16 个半角宽度截断并加省略号。

    宽度按终端惯例计算：中文等全角字符算 2，字母数字算 1，所以 8 个汉字与
    16 个字母都正好占满上限。昵称本身在存储里保持完整（账号昵称、参与身份
    快照、消息留档都不改写），只有发往界面的字符串走这里。主持人展示名是
    「主持人(昵称)」这种组合标签，截断时只动括号里的昵称，不能把「主持人(」
    也截掉。
    """
    text = (name or "").strip()
    if text.startswith(HOST_LABEL_PREFIX) and text.endswith(")"):
        inner = text[len(HOST_LABEL_PREFIX) : -1]
        return f"{HOST_LABEL_PREFIX}{display_player_name(inner, limit)})"
    used = sum(_name_width(char) for char in text)
    if used <= limit:
        return text
    kept = []
    used = 0
    for char in text:
        width = _name_width(char)
        if used + width > limit:
            break
        kept.append(char)
        used += width
    return "".join(kept) + "…"


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
    # 候场时这里就是玩家的公开称呼：选择界面上的展示同样受 16 半角宽度上限约束。
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


def witch_destiny_notice(game, seat_id):
    """「魔女化命运」的文案：发牌私信与「我的」页状态卡共用同一份，避免两处口径漂移。

    A、B 两席说清当值日；艾玛席只能给条件式预告——艾玛按最高优先级魔女化，
    但只有她当天以当前牌登场才算数，说成必定兑现会与第三天的实际结果打架。
    """
    destiny = game["public"].get("witch_destiny") or {}
    faction = list(destiny.get("first", []))
    if seat_id in faction:
        return f"你是魔女阵营：第{faction.index(seat_id) + 1}天你的当前牌会魔女化。"
    seats = destiny.get("seats") or []
    if int(seat_id) <= len(seats) and seats[int(seat_id) - 1]:
        return "本局你会魔女化：第三天如果你的当前牌是艾玛，她将以最高优先级魔女化。"
    return "前三天你不会按开局命运魔女化。"


def hanna_witch_window(game):
    """「汉娜魔化」开关只在第三天入夜前可调；第三天当晚的检测尚未结算时仍可补开。"""
    return game["status"] == "playing" and (
        game["day"] < 3 or (game["day"] == 3 and game["phase"] == "witch")
    )


def player_seat(game, actor):
    require(
        actor.get("kind") == "player" and actor.get("game_id") == game["id"], "没有玩家操作权限"
    )
    s = seat(game, actor.get("seat_id"))
    require(s["occupant_id"] == actor.get("id"), "该席位已更换操作者")
    return s


def puppet_master_card(game, card):
    """傀儡状态里记着的那张主人牌；不判断它现在还能不能控制。"""
    return game["cards"].get(card["states"].get("puppet") or "")


def puppet_master_dead(game, card):
    """主人是否已经离场：牌不存在、出局，或不再是魔女牌。

    用户 2026-09-28 定的规则：梅露露死亡后傀儡当前牌立即死亡，所以这个判据要能与
    「主人还在、只是不再是自己席位的当前牌」区分开（后者只解除控制，不处死傀儡）。
    """
    master = puppet_master_card(game, card)
    return master is None or not master["alive"] or not master["witch"]


def puppet_master(game, card):
    """当前控制该傀儡牌的魔女梅露露牌；控制关系已撤销或主人已出局时返回 None。

    主人还必须仍是自己席位的**当前牌**：主人换牌后它连自己的行动都提交不了，更谈不上
    代操作；这种傀儡由 :func:`orphan_puppet_cards` 判定为「无人控制」并解除。
    """
    master = puppet_master_card(game, card)
    if master is None or not master["alive"] or not master["witch"]:
        return None
    return master if current(game, owner(game, master["id"])) == master else None


def puppet_controlled_by(game, card, seat_id):
    """该牌是否正由 seat_id 席位的魔女梅露露控制。"""
    master = puppet_master(game, card)
    if master is None:
        return False
    return owner(game, master["id"])["id"] == seat_id


def puppet_cards(game):
    """全部仍挂着傀儡状态的牌（含已出局、已不是当前牌的历史残留）。"""
    return [card for card in game["cards"].values() if card["states"].get("puppet")]


def orphan_puppet_cards(game):
    """控制链已经断了的傀儡牌；由 engine.sync_puppet_bonds 收拾。

    两种：主人已经不能代操作（出局/失去魔女身份/不再是自己席位的当前牌），或者这张
    牌自己已不是该席位的当前牌（控制者面板也拿不到它）。主人真的离场时那张当前牌
    还要跟着当场出局，见 :func:`puppet_master_dead`。
    """
    result = []
    for card in puppet_cards(game):
        if puppet_master(game, card) is None or current(game, owner(game, card["id"])) != card:
            result.append(card)
    return result


def release_puppet(card):
    """解除一张牌的傀儡状态（连同「无技能」标记）；返回它原本是不是傀儡。"""
    was_puppet = bool(card["states"].get("puppet"))
    card["states"].pop("puppet", None)
    card["states"].pop("no_ability", None)
    return was_puppet


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


# 被动技能的播报卡片：与白天技能播报同款，只换样式区分（客户端按 mode 判定）。
# 元组是（角色牌 id、技能名、公开介绍），介绍逐句取自 CATALOG 里已公开的角色说明。
PASSIVE_CARDS = {
    "gaze": (
        "nanoka",
        "处决幻视",
        "处决名单一定下来后，无论最终是否有人被处决，都会自动幻视本日名单是否含魔女，结果只发给你；"
        "这是被动技能，不必也不能声明发动。",
    ),
    "rewind": (
        "hiro",
        "时间回溯",
        "即将出局时自动回溯一次（本局该身份一次）：回到前一天并保留记忆与普通技能，"
        "精神系效果不恢复；艾玛全场攻击生效的这一夜不触发普通或魔女回溯，也不消耗额度。",
    ),
    "bind": (
        "sherry",
        "雪莉绑定",
        "与汉娜绑定：胜负跟随汉娜，不能同意处决汉娜；汉娜被处刑时殉情。",
    ),
    "substitute": (
        "millia",
        "米莉亚替死",
        "被换血的目标真的会出局时，不再需要你确认，由你代替其出局。",
    ),
    "love": (
        "marg",
        "爱人庇护",
        "爱人免疫处决、临刑开枪、魔女刀与13水等一切死亡和其他负伤。",
    ),
    "love_self": (
        "marg",
        "转爱自己",
        "被爱的那张牌出局后，你转爱自己，庇护随之落到自己身上。",
    ),
}


def passive_card_payload(game, key, effect, seat_id=None, public=False):
    """被动技能生效的播报载荷：``effect`` 是这一次自动结算的具体内容。

    卡片本身不判断可见性——载荷里的结果多半属于私密情报（处决幻视的结果、被换血的
    对象、被爱的牌），所以调用方必须只把这条消息发给技能本人：``notify(..., seats=[sid])``
    决定收件人，主持人照旧由 storage.visible_message 的主持人旁路看到全文，
    其余玩家根本收不到这条消息。``effect`` 的下发另外由 ``public`` 控制：只有整局
    都看得见的结果（例如时间回溯）才置 True，storage.project_message_payload 会据此
    决定是否把结果文本下发给非本人。
    """
    role_id, ability_name, intro = PASSIVE_CARDS[key]
    card = game["cards"].get(role_id)
    if card is None:
        return None
    sid = seat_id or owner(game, card["id"])["id"]
    row = seat(game, sid)
    return {
        "type": "skill",
        "mode": "passive",
        "ability": key,
        "ability_name": ability_name,
        "role_id": role_id,
        "_animation": skill_animation_snapshot(role_id, key, ability_name, card["witch"]),
        "role_name": ROLES.get(role_id, {}).get("name", role_id),
        "intro": intro,
        "effect": effect,
        "effect_public": bool(public),
        "seat_id": sid,
        "actor_participant_id": row["occupant_id"] if row else None,
        "actor_name": display_player_name(row["name"] if row else ""),
        # 被动技能不可质疑、不可伪装，也没有目标：字段补齐只为复用同一张卡片。
        "challengeable": False,
        "target_public": False,
        "target": None,
        "fake": False,
        "card_id": card["id"],
    }


def death_card_entry(game, row, before, water=False):
    """角色卡死亡卡片的一条。

    只放已经公开的信息：席位号、展示名、死亡时的公开头像与「是否被13水毒杀」。
    真实牌 id 与死因一律不进载荷——13 水的隐藏死因、穗乃香的示人身份、殉情与替死
    都不该由这张卡片泄露；需要死因的是主持人视图，那里另有完整记录。
    角色名按**公开头像**取，不按真实牌：示人的穗乃香出局时卡片必须继续显示她示人的角色。
    """
    public_role = before.get("avatar_role_id")
    return {
        "seat_id": row["id"],
        "player_name": display_player_name(row.get("name", "")),
        "avatar_role_id": public_role,
        "role_name": ROLES.get(public_role or "", {}).get("name", public_role or ""),
        "water": bool(water),
    }


# 死亡卡片允许下发的字段：白名单而不是黑名单，将来往条目里加内部字段（例如 death_id）
# 也不会顺着载荷漏给玩家。
DEATH_CARD_KEYS = ("seat_id", "player_name", "avatar_role_id", "role_name", "water")


def death_card_payload(game, entries, half=None, day=None):
    """死亡卡片载荷：一夜的出局合并成一张卡，与「天亮只发一条汇总」同一口径。"""
    return {
        "type": "death",
        "day": day if day is not None else game["day"],
        "half": half if half is not None else game["half"],
        "deaths": [
            {key: entry[key] for key in DEATH_CARD_KEYS if key in entry} for entry in entries
        ],
    }


def notify(
    game,
    events,
    text,
    seats=None,
    title="游戏信息",
    image_id=None,
    alert=False,
    payload=None,
    reference_title=None,
):
    recipients = None if seats is None else audience(game, seats)
    event = {
        "kind": "information" if recipients is not None else ("alert" if alert else "notice"),
        "text": text,
        "audience": recipients,
        "title": title,
    }
    if reference_title is not None and recipients is None:
        event["reference_title"] = reference_title
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


# 主持人对局日志：进行中只给主持人看，归档后公开完整有效记录。
# 追加统一的 {day, half, phase, kind, text} 条目，客户端按 kind 着色。


def log_event(game, kind, text):
    entry = {
        "day": game["day"],
        "half": game["half"],
        "phase": game["phase"],
        "kind": kind,
        "text": text,
    }
    game.setdefault("log", []).append(entry)


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
    order = dict.fromkeys(game["public"].get("speech_order", []) + [s["id"] for s in game["seats"]])
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


def eligible_voters(game, context=None):
    """Voting seats after enabled rules; original no-vote and control criteria stay core."""
    from .plugins import emit

    voters = [
        s
        for s in living(game)
        if (
            not (card := current(game, s))["states"].get("puppet")
            or puppet_master(game, card) is not None
        )
        and not card["states"].get("no_vote")
        and annan_penalty_day(game, s["id"]) != game["day"]
    ]
    selection = {"voters": voters, "excluded_puppets": 0, "excluded_puppet_seats": []}
    emit(game, [], "vote_eligibility", selection)
    if context is not None:
        context.update(selection)
    return selection["voters"]


def vote_denominator(game):
    """本次投票的分母：投票开始时冻结，之后中途有人出局也不再改变它。

    分母同时决定「严格过半」与蕾雅决斗的「半数」门槛。冻结前它随存活人数浮动，
    会让已经下发到玩家表单上的门槛在计票那一刻悄悄变掉。
    """
    frozen = game.get("vote_freeze") or {}
    if frozen.get("day") == game["day"] and frozen.get("denominator"):
        return frozen["denominator"]
    return len(eligible_voters(game))


def surrendered_seats_today(game):
    """今天已经私信主持人申请本阵营交牌的席位。

    交牌意向按「席位 + 当天」记账：跨天自动失效，席位也不再因为被魔典兜底转化为
    魔女而沿用一条陈旧的同意（旧版只存席位号，会跨天、跨阵营复用）。
    """
    return [
        item["seat"]
        for item in game.get("surrenders") or []
        if isinstance(item, dict) and item.get("day") == game["day"]
    ]


def surrendered_today(game, seat_id):
    return seat_id in surrendered_seats_today(game)


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


def seat_choice(game, seat_id, card_id):
    """该席位对某个候选已提交的选择；尚未投票时返回 None。"""
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
        seat_choice(game, seat_id, item["card_id"]) is not None for item in nomination_rounds(game)
    )


def poison_sources(game, card):
    """返回主持人可见的动态中毒来源；玩家只看到中毒结论。"""
    sources = []
    if card["states"].get("poisoned"):
        sources.append("主持人状态")
    target_seat = next((s for s in game["seats"] if card["id"] in s["cards"]), None)
    if emma.poison_exposed(game, card):
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


def can_use_ability(game, card, puppet_controlled=False):
    """当前牌此刻能否**发动角色技能**。

    傀儡可以代行投票、发言、提名与被动的临刑确认，但规则明令「不能发动技能」，
    所以 ``no_ability``（复活成傀儡时打上）在技能入口一律生效——它比
    :func:`can_use_card` 严格，且不因为控制者代操作而放宽。
    """
    if not card or card["states"].get("no_ability"):
        return False
    return can_use_card(game, card, puppet_controlled)


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


def revive_declined(game):
    """本夜梅露露是否已经放弃复活。

    ``game["night"]`` 每夜重建，所以这个标记天然只对本夜有效；30秒警告超时与
    主持人的强制推进（推进＝视为放弃）都会写它，写完之后复活入口随之关闭。
    """
    return bool((game.get("night") or {}).get("revive_declined"))


def revive_deaths(game):
    """当夜由这张梅露露牌造成、且尚未被处理的死亡；没有则空表。"""
    meruru = role_card(game, "meruru")
    return [
        death
        for death in game["deaths"]
        if death["day"] == game["day"]
        and death["half"] == "night"
        and death.get("source_card") == meruru["id"]
        and not game["cards"][death["target_card"]]["alive"]
    ]


def pending_revive(game):
    """当夜仍可用、但本人还没决定的梅露露席位；没有则返回 None。

    条件是 ``actions_for`` 里那枚「复活」按钮的同一套（当夜、魔女化、本局次数未用、
    当夜仍有由这张牌造成的死亡），只多一条「本人还没放弃」。两处必须同一口径，
    否则会出现「按钮还在、主持人却看不到待办」或反过来「待办挡着、按钮已经没了」。
    """
    if game["status"] != "playing" or game["half"] != "night" or revive_declined(game):
        return None
    meruru = role_card(game, "meruru")
    if not meruru["witch"] or meruru["uses"].get("revive"):
        return None
    if not can_use_card(game, meruru):
        return None
    if not revive_deaths(game):
        return None
    return owner(game, "meruru")["id"]


# 不允许发到同一席位的角色对：每对的两个角色牌序索引 //2 必须不同。
# 米莉亚与希罗同席时，米莉亚夜间临死换牌可能把希罗牌换走、希罗的回溯时点跟着错乱，
# 规则上不允许两人同一天挤在同一席位。
DEAL_EXCLUDED_PAIRS = (
    ("millia", "arisa"),
    ("coco", "sherry"),
    ("millia", "hiro"),
    ("emma", "noah"),
    ("hanna", "emma"),
)

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
    # 第2天 B 的当前牌魔女化，第3天由 A、B 中可选的一位接替。持有艾玛、
    # 米莉亚、亚里沙或雪莉的席位不能进命运，从其余席位里抽。
    emma_seat = order.index("emma") // 2
    ineligible = {
        i
        for i in range(7)
        if i == emma_seat or {order[i * 2], order[i * 2 + 1]} & {"millia", "arisa", "sherry"}
    }
    eligible_seats = [i for i in range(7) if i not in ineligible]
    first = rng.sample(eligible_seats, 2) if len(eligible_seats) >= 2 else eligible_seats
    # 艾玛席第三天以当前牌登场时按最高优先级魔女化，所以本人也要拿到一份
    # 条件式预告（见 witch_destiny_notice）；这里只写入逐席布尔值：客户端只读
    # 自己那一位，不再单独下发艾玛席号，否则调序阶段就会把「哪一席是艾玛」
    # 提前公开。first 是按当值顺序排列的魔女阵营 A、B 席位，胜负与第三天补位都读它。
    destiny = [i in first or i == emma_seat for i in range(7)]
    game["public"]["witch_destiny"] = {
        "seats": destiny,
        "first": [str(i + 1) for i in first],
    }
    start_phase(game, "ordering")


def upgrade_game(game):
    """就地补齐第六版规则字段；保留旧局的全部历史数据。"""
    changed = game.get("rules_revision") != 6
    from .plugins import required_manifest

    add_manifest = required_manifest()
    if "rule_plugins" not in game:
        game["rule_plugins"] = add_manifest
        changed = True
    if "plugin_state" not in game:
        game["plugin_state"] = {}
        changed = True
    for snapshot in game.get("snapshots", []):
        if "plugin_state" not in snapshot["state"]:
            snapshot["state"]["plugin_state"] = {}
            changed = True
        if "rule_plugins" in snapshot["state"]:
            del snapshot["state"]["rule_plugins"]
            changed = True

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
        "revive_declined": False,
    }.items():
        add(night, key, value)
    # 「汉娜魔化」是主持人开关，默认关闭；旧局补齐为关。
    add(game, "hanna_witch", False)
    # 主持人身份快照与「已确认进入管理界面」的主持账号：旧局补齐为「没有记录」。
    add(game, "host", None)
    add(game, "host_entries", [])
    add(game, "queued_deaths", [])
    # 旧字段名只是同一份记录的前身（当时只用来给通告去重），合并后丢掉。
    legacy_entries = game.pop("host_entry_notices", None)
    if legacy_entries:
        game["host_entries"] = list(dict.fromkeys([*game["host_entries"], *legacy_entries]))
        changed = True
    legacy_actions = [
        action for action in night["actions"] if action.get("ability") not in NIGHT_ABILITIES
    ]
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
    # 旧存档缺少阶段起点时只补一次；storage.load_game 会持久化这次补齐。
    add(public, "phase_started_at", clock.now())
    add(public, "declarations", [])
    add(public, "witch_destiny", None)
    # 顺序发言的30秒倒计时是新加字段：旧局补齐为「还没有倒计时」，
    # 下一次时钟检查（或轮到下一位）会按当前发言人重新建立。
    add(public, "speech_deadline", None)
    add(public, "speech_deadline_seat", None)
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
    # 处决阶段的临刑枪字段此前只由 open_vote 创建：停在处决阶段的旧存档缺这两个键时，
    # 奈乃香开枪会因写 execution_shots 报错（advance 读的是 .get，所以只有枪会崩）。
    add(game, "execution_shots", [])
    add(game, "execution_rolls", [])
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
    add(game, "vote_freeze", None)
    # 交牌意向由「席位号列表」改为「{席位, 日期}」记录，只对当天有效。旧格式分不清
    # 日期与阵营，留着它就是把「陈旧意向被跨天、跨阵营复用」的缺陷一起留下，因此
    # 停在旧局的意向直接丢弃，当事人重新点一次即可。
    if any(isinstance(item, str) for item in game.get("surrenders") or []):
        game["surrenders"] = [item for item in game["surrenders"] if isinstance(item, dict)]
        changed = True
    # 热气球玩法已整体移除：停在热气球阶段的旧局直接改判为提名，并清掉该玩法的
    # 全部状态，否则旧阶段名与旧技能会在 PHASES／DAY_ABILITIES 里查表失败。
    if game.get("phase") == "balloon":
        start_phase(game, "nomination")
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
    # 傀儡与「无技能」必须成对：旧存档（修复前保存的对局）只有 puppet 标记，
    # 补上 no_ability 才不会让升级后的傀儡继续发动角色技能。
    for card in (game.get("cards") or {}).values():
        if card["states"].get("puppet") and not card["states"].get("no_ability"):
            card["states"]["no_ability"] = True
            changed = True
    for states in (spiritual.get("persistent_states") or {}).values():
        if states.get("puppet") and not states.get("no_ability"):
            states["no_ability"] = True
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


def create_game(codex, rule_plugins=None):
    require(
        isinstance(codex, list)
        and len(codex) == 11
        and all(isinstance(r, str) and r in ROLES for r in codex)
        and len(set(codex)) == 11,
        "请确认11名不重复的魔典角色",
    )
    shuffled_codex = list(codex)
    SystemRandom().shuffle(shuffled_codex)
    from .plugins import manifest

    return {
        "id": uid(),
        "rules_revision": 6,
        "rule_plugins": manifest(rule_plugins),
        "plugin_state": {},
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
            # 本夜梅露露是否已经放弃复活（30秒警告超时或主持人推进＝放弃）；每夜重建。
            "revive_declined": False,
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
            "phase_started_at": clock.now(),
            "speaker": None,
            "speech_order": [],
            "votes": {},
            "declarations": [],
            "rewinds": 0,
            # 顺序发言的30秒公开倒计时（Unix 秒）与它归属的席位；不在发言阶段时为 None。
            "speech_deadline": None,
            "speech_deadline_seat": None,
        },
        "nominations": [],
        "speech_passed": [],
        "speech_queued": {},
        "queued_notices": [],
        "queued_reveals": [],
        # 夜间死亡卡片的载荷：与 queued_notices 一一对应，天亮时随汇总公告一起下发；
        # 被梅露露复活的死亡由 revoke_death 一并删掉。
        "queued_deaths": [],
        # 今天已提交的选票：{席位: {角色牌: 同意/不同意/弃票}}。
        "ballots": {},
        "vote_rounds": [],
        # 本次投票开始时冻结的分母（见 vote_denominator）；投票结束清空。
        "vote_freeze": None,
        "execution": [],
        "execution_ready": [],
        # 本日处决阶段的临刑开枪：已提交的射击与每次掷骰。落在处决阶段的旧存档可能
        # 没有这两个键（此前只在 open_vote 里创建），因此 upgrade_game 也要补齐，
        # 否则奈乃香开枪写 execution_shots 时会抛 KeyError。
        "execution_shots": [],
        "execution_rolls": [],
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
    "rule_plugins",
}


def fallen_upper_role(game, seat):
    """席位第一张牌已经出局时的角色，用于头像上的下牌标记与悬浮回顾。"""
    if len(seat["cards"]) < 2:
        return None
    upper = game["cards"][seat["cards"][0]]
    return None if upper["alive"] else upper["role_id"]


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


def refresh_seat_avatar(game, s):
    """按当前牌重算席位公开头像。

    seats 不随快照还原（占位身份与公开形象属于真实时间），但头像必须与当前牌
    一致：回溯恢复上层牌后，曾经因上层出局而切到下层牌的席位要改回来。
    穗乃香示人锁定后头像继续用示人角色，与下层登场时的处理保持一致。
    """
    now = current(game, s)
    if now is None:
        return
    if now["id"] == "honoka" and now["states"].get("disguise_locked"):
        s["avatar_role_id"] = now["states"].get("disguise") or "honoka"
    else:
        s["avatar_role_id"] = now["role_id"]


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
        # 牌面已恢复到回溯点：曾经因上层出局切到下层牌的公开头像一并改回，
        # 否则当前牌是上层、头像却停在下层。
        refresh_seat_avatar(game, s)
    game["spiritual"] = spiritual
    for cid, states in spiritual["persistent_states"].items():
        game["cards"][cid]["states"].update(states)
        # 傀儡与「无技能」必须成对（旧存档里可能只记了 puppet）：回放持久状态后
        # 统一校准一次，免得回溯出一个「有主人但会发动技能」的傀儡。
        if states.get("puppet"):
            game["cards"][cid]["states"]["no_ability"] = True
        elif "puppet" in states:
            release_puppet(game["cards"][cid])
    for cid, states in retained.items():
        game["cards"][cid]["states"].update(states)
    if mode == "witch":
        role_card(game, "hiro")["witch"] = True
        if "hiro" not in game["generated_witches"]:
            game["generated_witches"].append("hiro")
    game["warnings"] = {}
    game["deadline"] = None
    start_phase(game, game["phase"])
    # 顺序发言的倒计时不跟着快照回到过去：回溯点里的截止时间早已过期，留着它
    # 会让恢复出来的发言人一秒钟内被自动顺延。丢掉后由引擎按恢复的发言人重新计时。
    game["public"].pop("speech_deadline", None)
    game["public"].pop("speech_deadline_seat", None)
    game["public"]["rewinds"] += 1
    # 日志是时间线的一部分：裁掉回溯点之后的条目，再记下这次回溯本身。
    if "log" in game and snap.get("log_index") is not None:
        del game["log"][snap["log_index"] :]
    log_event(game, "system", f"时间回溯到「{snap['label']}」，之后的时间线作废。")
    # 希罗的自动回溯是公开事件（整局时间线当面回退），公告本来就不区分是否本人：
    # 这里给同一句话补一张被动技能卡，让被动技能也有和白天技能一样的展示框。
    # 主持人手动回溯（mode 为空）没有对应技能，仍只发原来的文本公告。
    notice = "游戏时间已回溯；已经获得的信息与聊天记忆保留。"
    payload = None
    if mode:
        payload = passive_card_payload(game, "rewind", notice, public=True)
    notify(game, events, notice, payload=payload)


def witch_seats(game):
    """好人必须清空的魔女席位：命运席位 A、B，加上任何产生过魔女牌的席位。

    用户批注（A08）：好人胜利条件按「魔女牌全部出局」判定，并且包含第 4 天起由
    魔典转化的魔女牌。这里按席位记账而不是按单张牌：魔女牌出局后，同席的另一张
    牌仍会在后续白天按魔典／第三天规则再魔女化，只看单张牌会提前判好人获胜。
    """
    seats = set(witch_faction(game))
    for cid in game.get("generated_witches", []):
        if game["cards"].get(cid):
            seats.add(owner(game, cid)["id"])
    return seats


def emma_solo_win(game):
    """全场攻击正常结算后艾玛单胜，存活与实际死亡人数不影响胜负。

    massacre 在锁定后的预结算中记录；只有进入 night_results 才算正常结算。
    全场攻击生效的这一夜不触发希罗的普通或魔女回溯。
    """
    emma = role_card(game, "emma")
    return bool(
        emma["witch"]
        and game["half"] == "night"
        and game["phase"] == "night_results"
        and (game.get("night") or {}).get("massacre")
    )


def check_winner(game):
    if emma_solo_win(game):
        # 艾玛的单胜独立于两个阵营：她单独获胜，其余玩家均落败。
        game["winner_candidate"] = {
            "winner": "emma",
            "reason": "魔女化艾玛的全场攻击已正常结算，单独获胜，其余玩家均落败",
        }
        return
    faction = witch_faction(game)
    seats = witch_seats(game)
    good = bool(faction) and all(current(game, seat(game, sid)) is None for sid in seats)
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
            else "魔女牌全部出局（含魔典转化）"
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
        "对局结束："
        + (
            "好人胜利"
            if winner == "good"
            else "魔女胜利"
            if winner == "witch"
            else "艾玛单独获胜"
            if winner == "emma"
            else "主持人结束"
        )
        + f"（{reason}）",
    )
    notify(
        game,
        events,
        "对局结束："
        + (
            "好人"
            if winner == "good"
            else "魔女"
            if winner == "witch"
            else "艾玛单独获胜（其余玩家均落败）"
            if winner == "emma"
            else "主持人结束"
        )
        + f"。{reason}",
    )


def clear_seat_actions(game, seat_id, events=None):
    require(any(s["id"] == seat_id for s in game["seats"]), "席位不存在")
    night = game["night"]
    # 寻宝提交后本夜定局：不能清除，也不能借「放弃并确认」在私下看到结果后弃单。
    require(
        not any(a["seat_id"] == seat_id and a["ability"] == "treasure" for a in night["actions"]),
        "寻宝已提交，本夜不可修改或放弃",
    )
    night["actions"] = [a for a in night["actions"] if a["seat_id"] != seat_id]
    night["confirmed"] = [s for s in night["confirmed"] if s != seat_id]
    # 米莉亚清除本夜选择时，正在生效的换血目标也一并作废，避免留下没有行动记录的替死。
    if game.get("millia_swap") and owner(game, "millia")["id"] == seat_id:
        game["millia_swap"] = None
    if night.get("locked") and game["phase"] == "night_review":
        from .resolution import prepare_night_preview

        game["pending"] = [p for p in game["pending"] if p["kind"] != "hiro" or p.get("preview")]
        night["reactions"] = []
        # 重算预结算同样可能触发希罗回溯，事件队列要一起传下去（见 prepare_night_preview）。
        prepare_night_preview(game, events)
    game["warnings"].pop(seat_id, None)
    game["deadline"] = min(game["warnings"].values(), default=None)
