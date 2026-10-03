"""Game commands and phase flow; callers commit a copied state atomically."""

from copy import deepcopy
from random import SystemRandom

from . import clock
from . import plugins
from .roles import hanna, hiro, honoka, meruru, millia, nanoka, sherry
from .actions import (
    CHALLENGE_PHASES,
    actions_for,
    can_day_ability,
    challengeable,
    day_fake_allowed,
    discussion_end_reached,
    evidence_public_text,
    night_abilities,
    outstanding_seats,
)
from .animations import skill_animation_snapshot, speech_animation
from .catalog import (
    ABILITY_INTRO,
    ABILITY_NAMES,
    AUTO_ADVANCE_DELAY,
    AUTO_PHASES,
    DAY_ABILITIES,
    DISCUSSION_END_DELAY,
    NIGHT_ABILITIES,
    PHASES,
    POISON_EFFECT_ABILITIES,
    PUBLIC_TARGET_ABILITIES,
    ROLES,
    SPEECH_TURN_SECONDS,
)
from .resolution import (
    begin_night,
    death_batch,
    eliminate_seat,
    false_witness,
    lock_night,
    prepare_night_preview,
    publish_day_passives,
    publish_night_passives,
    revive,
    resolve_intents,
    sync_night_confirmations,
    target_allowed,
)
from .roles.coco import unlock_coco
from .state import (
    DEAL_LOWER_ROLES,
    GameError,
    audience,
    can_use_ability,
    card_actionable,
    chat_event,
    check_winner,
    clear_seat_actions,
    host_capable,
    host_view_actor,
    current,
    deal_cards,
    death_card_payload,
    debunked_abilities,
    display_player_name,
    duel_cards,
    duel_vote_required,
    eligible_voters,
    effect_effective,
    finish,
    hanna_witch_window,
    living,
    log_event,
    lost_by_challenge,
    nomination_rounds,
    pending_nominators,
    pending_revive,
    notify,
    owner,
    pending,
    player_seat,
    present,
    require,
    release_puppet,
    rewind,
    role_card,
    save_snapshot,
    seat,
    seat_choice,
    seat_operable,
    surrendered_today,
    uid,
    vote_denominator,
    witch_destiny_notice,
    witch_faction,
)


def validate_command(game, actor, action, payload):
    require(isinstance(action, str) and isinstance(payload, dict), "操作格式无效")
    require(actor.get("kind") in {"host", "player", "spectator"}, "没有操作权限")
    # 主持人要先确认进入本局管理界面，服务端才按主持人放行（见 state.host_capable）；
    # 未确认时连这里列出的行动表都是空的，命令无从通过。
    require(
        host_capable(actor) if actor.get("kind") == "host" else actor.get("game_id") == game["id"],
        "没有本局操作权限",
    )
    choices = [
        a
        for a in actions_for(
            game,
            host_view_actor(actor),
            puppet_controlled=bool(actor.get("puppet_controlled")),
        )
        if a["id"] == action and all(payload.get(k) == v for k, v in a["payload"].items())
    ]
    require(bool(choices), "此操作不可用，请刷新当前状态")
    descriptor = choices[0]
    require(descriptor.get("ui_version") == 1, "行动协议版本不受支持")
    require(
        all(
            field.get("type")
            in {"text", "textarea", "number", "select", "multiselect", "checkbox", "drawing"}
            for field in descriptor["fields"]
        ),
        "行动字段类型不受支持",
    )
    allowed = set(descriptor["payload"]) | {f["name"] for f in descriptor["fields"]}
    if "image" in allowed:
        allowed.add("image_id")
    require(not (set(payload) - allowed), "操作包含未允许的字段")
    for f in descriptor["fields"]:
        name = "image_id" if f["type"] == "drawing" else f["name"]
        value = payload.get(name)
        if value is None or value == "" or value == []:
            require(not f.get("required"), f"请填写{f['label']}")
            continue
        kind = f["type"]
        if kind == "checkbox":
            require(isinstance(value, bool), "请选择有效的是或否")
        elif kind == "number":
            require(isinstance(value, (int, float)) and not isinstance(value, bool), "数字格式无效")
            require(f.get("min", value) <= value <= f.get("max", value), "数字超出允许范围")
        elif kind in {"select", "multiselect"}:
            options = {o["value"] for o in f["options"]}
            values = value if kind == "multiselect" else [value]
            require(
                isinstance(values, list)
                and all(isinstance(v, str) and v in options for v in values),
                "选择的目标无效",
            )
            require(len(values) == len(set(values)), "选择不能重复")
            if kind == "multiselect":
                require(f.get("min", 0) <= len(values) <= f.get("max", 100), "选择数量不符合要求")
        else:
            require(
                isinstance(value, str) and len(value) <= (128 if kind == "drawing" else 4000),
                "文本或附件格式无效",
            )
    return descriptor


def set_witch(game, events, cid, *, forced=False):
    card = game["cards"][cid]
    if not forced:
        require(cid not in {"sherry", "arisa", "emma"}, "雪莉、亚里沙与艾玛不能通过普通路径魔女化")
    require(card["alive"] and not card["witch"], "该角色不能再次魔女化")
    card["witch"] = True
    if cid not in game["generated_witches"]:
        game["generated_witches"].append(cid)
    notify(
        game,
        events,
        "你的当前角色已魔女化；每夜可独立选择魔女刀。",
        [owner(game, cid)["id"]],
        "魔女化",
    )


def convert_daily(game, events):
    if game.get("witch_checked_day") == game["day"]:
        # 本日已检测过：主持人纠错改动状态后不再次自动转化，直接开夜。
        begin_night(game, events)
        return
    game["witch_checked_day"] = game["day"]
    destiny = game["public"].get("witch_destiny")
    day = game["day"]
    conversion = {"day": day, "skip": False}
    plugins.emit(game, events, "witch_conversion", conversion)
    if conversion["skip"]:
        begin_night(game, events)
        return

    def legal(cid):
        c = game["cards"][cid]
        s = owner(game, cid)
        other = next(game["cards"][x] for x in s["cards"] if x != cid)
        return (
            cid not in {"sherry", "arisa", "emma"}
            and c["alive"]
            and not c["witch"]
            and current(game, s) == c
            and other["original_role_id"] not in {"millia", "arisa"}
        )

    converted = False
    if day == 3:
        # 第三天：**当前牌是艾玛**的那个席位以最高优先级成为当天魔女。她还在下层、尚未
        # 登场时不算——否则会出现「没有刀可点的魔女」，私信里「你的当前角色已魔女化」
        # 也变成假话，还会泄露「被转化的是我另一张隐藏牌」。
        # 「汉娜魔化」五条全部成立时由汉娜覆盖该人选（条件里已含艾玛不在场）；以上都不
        # 成立时，改由魔女阵营 A、B 中仍可转化的一位接替，不再退回魔典。
        if hanna.witch_override(game):
            if not game["cards"]["hanna"]["witch"]:
                set_witch(game, events, "hanna")
                log_event(game, "system", "「汉娜魔化」生效：第三天夜的魔女人选由汉娜承担。")
            converted = True
        elif present(game, "emma"):
            if not game["cards"]["emma"]["witch"]:
                set_witch(game, events, "emma", forced=True)
            converted = True
        else:
            for sid in sorted(witch_faction(game), key=int):
                card = current(game, seat(game, sid))
                if card and legal(card["id"]):
                    set_witch(game, events, card["id"])
                    converted = True
                    break
    elif destiny and day < 3:
        if day - 1 < len(destiny["first"]):
            s = seat(game, destiny["first"][day - 1])
            card = current(game, s)
            if card and legal(card["id"]):
                set_witch(game, events, card["id"])
                converted = True
    if not converted and day != 3:
        # 命运席位当前牌不可转化（雪莉当道、亚里沙/米莉亚同席、已出局等）时，
        # 退回魔典顺序找第一个合法目标；仍无目标才交主持人裁定。
        for cid in game["codex"]:
            if legal(cid):
                set_witch(game, events, cid)
                converted = True
                break
    if not converted:
        if day == 3:
            log_event(
                game,
                "system",
                "第三天没有以当前牌登场的艾玛，且魔女阵营无可转化目标，本夜不产生新的魔女。",
            )
        else:
            pending(game, "codex", "本日无合法魔女化目标：主持人裁定转化或耗尽处理")
            return
    begin_night(game, events)


def apply_damage(game, events, preview, allow_reaction=True):
    """结算一次伤害；希罗缺阵时按固定时点自动回溯并返回 True。"""
    hiro_card = role_card(game, "hiro")
    half = game["half"]
    mode = "witch" if hiro_card["witch"] else "normal"
    hiro_triggered = (
        allow_reaction
        and not game["spiritual"]["hiro_used"][mode]
        and any(death["target_card"] == "hiro" for death in preview["deaths"])
    )
    if hiro_triggered:
        if hiro.rewind_on_death(game, events, half):
            return True
    if game["half"] == "night":
        # 夜间的被动播报一律压到天亮（见 publish_night_passives），这里只把事实记在
        # 本夜的预结算结果上；night 属于对局状态，希罗回溯会连同它一起还原。
        game.setdefault("night", {})["love_blocked"] = list(preview.get("love_blocked") or [])
    death_batch(game, events, preview)
    if game["half"] != "night":
        # 白天出局当场公示，被动技能的播报卡片与死亡公告同一时刻发。
        publish_day_passives(game, events, preview)
    return False


def publish_speech_turn(game, events, seat_id):
    """把发言权起点存进消息时间线；头像用当时公开身份，不依赖之后的阶段或替补。"""
    turn = [game["day"], game["public"].get("rewinds", 0), seat_id]
    if game.get("speech_turn") == turn:
        return False
    s = seat(game, seat_id)
    events.append(
        {
            "kind": "speech_turn",
            "text": f"{seat_id}号开始顺序发言。",
            "payload": {
                "type": "speech_turn",
                "day": game["day"],
                "seat_id": seat_id,
                "avatar_role_id": s["avatar_role_id"],
                "animation": speech_animation(),
            },
        }
    )
    game["speech_turn"] = turn
    return True


def speech_done(game, events):
    public = game["public"]
    # 发言权一换人，原发言人的30秒警告就作废：新发言人另有一份公开倒计时，
    # 留着旧警告只会在30秒后给已经讲完的人补发一条「警告时间已到」的私信。
    if public.get("speaker") in game["warnings"]:
        game["warnings"].pop(public["speaker"], None)
        game["deadline"] = min(game["warnings"].values(), default=None)
    finished = public.get("speaker")
    if finished:
        # 轮次结束就记进 speech_passed，作为「本轮已处理」的统一口径：发言权顺延后
        # 他既拿不到「本轮不发言／提前写发言」这两个预提交入口，也不能借旧表单再提交一次。
        passed = game.setdefault("speech_passed", [])
        if finished not in passed:
            passed.append(finished)
    if public.get("interrupted_speaker"):
        resumed = public.pop("interrupted_speaker")
        publish_speech_turn(game, events, resumed)
        queued = game.get("speech_queued", {})
        if resumed in queued:
            # 被打断者若已提前写好发言，恢复发言权时先公开，内容不随打断丢失。
            chat_event(game, events, resumed, f"{queued.pop(resumed)}")
        public["speaker"] = resumed
        return
    public["speaker"] = next_speaker(game, public["speaker"], events)


def next_speaker(game, current_speaker, events):
    """下一位发言人；提前发言的席位在此刻才公开内容，宣布不发言或已出局的直接跳过。"""
    order = game["public"]["speech_order"]
    passed = set(game.get("speech_passed", []))
    queued = game.get("speech_queued", {})
    index = order.index(current_speaker) + 1 if current_speaker in order else 0
    # 用 seat_operable 而不是「有当前牌」：傀儡主人出局后该席无人可代操作，
    # 若仍排它发言就会卡死在「当前发言人」上。发言本身不需要牌面技能，故不看技能。
    while index < len(order) and (order[index] in passed or not seat_operable(game, order[index])):
        sid = order[index]
        if sid in queued:
            publish_speech_turn(game, events, sid)
            # 跳过或轮到自己前已出局：提前写好的内容照旧公开，不静默丢弃。
            chat_event(game, events, sid, f"{queued.pop(sid)}")
        index += 1
    speaker = order[index] if index < len(order) else None
    if speaker:
        publish_speech_turn(game, events, speaker)
    return speaker


def sync_speaker(game, events):
    """当前发言人已无人可操作时顺延到下一位；整轮无人可言则收尾。

    傀儡主人出局、两张牌同时出局等都可能让「当前发言人」在发言中途变成无人可操作。
    这类席位既拿不到发言按钮，也不该让阶段停住，必须在这里统一顺延。用 while 保证
    连续多个无人可操作的席位在一次调用里全部越过。
    """
    if game["phase"] != "speech":
        game.pop("speech_turn", None)
        # 离开顺序发言阶段：倒计时随阶段一起清除，不留到自由发言或第二天。
        if sync_speech_timer(game):
            game["version"] += 1
        return
    public = game["public"]
    while public.get("speaker") and not seat_operable(game, public["speaker"]):
        speech_done(game, events)
    if public.get("speaker") and publish_speech_turn(game, events, public["speaker"]):
        game["version"] += 1
    if sync_speech_timer(game):
        game["version"] += 1


def sync_speech_timer(game, now=None, reset=False):
    """顺序发言的30秒公开倒计时：换人就重新计时，本人继续发言也能拨满。

    倒计时挂在 ``public`` 里随状态下发，全场都看得到「还剩几秒」。返回值表示这次
    调用是否改动了倒计时，调用方据此决定要不要抬版本号并落库。
    """
    public = game["public"]
    speaker = public.get("speaker") if game["phase"] == "speech" else None
    if not speaker:
        changed = public.pop("speech_deadline", None) is not None
        public.pop("speech_deadline_seat", None)
        return changed
    now = clock.now() if now is None else now
    if reset or public.get("speech_deadline_seat") != speaker or not public.get("speech_deadline"):
        public["speech_deadline"] = now + SPEECH_TURN_SECONDS
        public["speech_deadline_seat"] = speaker
        return True
    return False


def touch_speech_timer(game, seat_id, now=None):
    """当前发言人发言或继续输入：把倒计时重新拨满；返回是否改动了它。

    只动公开倒计时，不抬版本号。输入状态是瞬态信号、每次输入都会刷新，若每次都抬
    版本号，别人正在提交的行动会被频繁判成「状态已变化」；延长倒计时不影响任何人的
    行动权限，所以调用方自己落库并推送状态即可。
    """
    if game["status"] != "playing" or game["phase"] != "speech":
        return False
    if not seat_id or game["public"].get("speaker") != seat_id:
        return False
    return sync_speech_timer(game, now=now, reset=True)


def run_speech_timer(game, now=None):
    """时钟每秒调用：维护倒计时；到点把发言权顺延到下一位并重新计时。

    与主持人的「警告」是两套计时：警告只私下通知被警告的席位，这里到点就直接换人。
    """
    if game["status"] != "playing":
        return []
    now = clock.now() if now is None else now
    events = []
    # 当前发言人若已无人可操作（出局、换牌），先按既有规则顺延；顺延会重建倒计时。
    sync_speaker(game, events)
    public = game["public"]
    if game["phase"] != "speech" or not public.get("speaker"):
        return events
    if public["speech_deadline"] > now:
        return events
    speech_done(game, events)
    sync_speech_timer(game, now)
    game["version"] += 1
    return events


def speech_plan(game, dead_first):
    """死者先发言；其余在顺序与逆序间取让魔女化玩家更早发言的一侧。

    两张牌都已出局的席位不再发言，不占本轮顺序；傀儡席在主人在场时仍由主人代发言。
    """
    seats = [s["id"] for s in living(game) if seat_operable(game, s["id"])]
    dead = [sid for sid in seats if sid in set(dead_first)]
    anchor = seats.index(dead[-1] if dead else seats[0])
    witches = {
        s["id"] for s in game["seats"] if (card := current(game, s)) is not None and card["witch"]
    }

    def walk(step):
        visited = [seats[(anchor + step * k) % len(seats)] for k in range(len(seats))]
        return dead + [sid for sid in visited if sid not in set(dead)]

    def rank(order):
        found = [order.index(sid) for sid in witches if sid in order]
        return min(found) if found else len(order)

    ascending, descending = walk(1), walk(-1)
    return ascending if rank(ascending) <= rank(descending) else descending


def enter_execution(game, events):
    """把当天的处决名单定下来并进入处决阶段。

    投票轮次跑完之后调用。安安的「洗脑全场」按用户批注（B14）是「你也被处决，且今天
    不能处决其他人」，它只把两张牌塞进名单并写 ``execution_lock``；这里再按锁把投票
    选出来的其他候选剔掉，所以洗脑当天同样只有那两张牌会被处决。
    """
    # 安安后果按席位记账：该席的当前牌直接进处决名单，换过当前牌也一样。
    for seat_id, penalty in game["spiritual"]["annan_penalty"].items():
        day = penalty.get("day") if isinstance(penalty, dict) else penalty
        if day != game["day"]:
            continue
        card = current(game, seat_id) if any(s["id"] == seat_id for s in game["seats"]) else None
        if card and card["id"] not in game["execution"]:
            game["execution"].append(card["id"])
    lock = game.get("execution_lock") or {}
    if lock.get("day") == game["day"]:
        # 洗脑后的当天：只有被洗脑者与安安本人会被处决，投票选出的其他候选不执行。
        game["execution"] = [cid for cid in game["execution"] if cid in lock["cards"]]
    # 名单到这里才算定稿：奈乃香的被动幻视就在这一刻自动结算（见 auto_gaze）。
    previous = game["phase"]
    nanoka.auto_gaze(game, events)
    if game["phase"] != "execution":
        # 奈乃香的命中率只在她自己的这一次处决里递增：刚进入处决阶段时清零，
        # 不留「上一轮残留让第一枪就是高命中」这个隐式前提。
        nanoka_card = game["cards"].get("nanoka")
        if nanoka_card:
            nanoka_card["uses"]["shot_misses"] = 0
    game["phase"] = "execution"
    game["execution_ready"] = []
    game["execution_shots"] = []
    game["public"]["votes"]["execution_seats"] = list(
        dict.fromkeys(owner(game, cid)["id"] for cid in game["execution"])
    )
    # 本日投票结束：解除分母冻结，下一轮投票重新按当时在场的有投票权人数算。
    game["vote_freeze"] = None
    plugins.emit(
        game, events, "phase_enter", {"from": previous, "to": "execution", "day": game["day"]}
    )


def open_vote(game, events):
    rounds = nomination_rounds(game)
    if duel_cards(game):
        # 投票一开始就把当天的决斗固定下来：候选表排定后不再随出局变化。
        game["duel"]["locked"] = True
    index = len(game["vote_rounds"])
    if index >= len(rounds):
        enter_execution(game, events)
        return
    game["phase"] = "voting"
    # 投票一开始就冻结分母：轮次表、门槛都按这一刻有投票权的人数算，中途有人出局也
    # 不会让已经下发到玩家表单上的票数门槛在计票时悄悄变掉（见 state.vote_denominator）。
    frozen = game.get("vote_freeze") or {}
    if frozen.get("day") != game["day"] or not frozen.get("denominator"):
        eligibility = {}
        voters = eligible_voters(game, eligibility)
        game["vote_freeze"] = {
            "day": game["day"],
            "denominator": len(voters),
            "excluded_puppets": eligibility["excluded_puppets"],
            "excluded_puppet_seats": eligibility["excluded_puppet_seats"],
        }
    game["public"]["votes"] = {
        "candidates": [{"seat_id": item["seat_id"], "card_id": item["card_id"]} for item in rounds],
        "total": len(rounds),
        "results": deepcopy(game["vote_rounds"]),
    }
    if index == 0:
        duel = duel_cards(game)
        notify(
            game,
            events,
            f"开始投票：本轮候选{len(rounds)}名（"
            + "、".join(f"{item['seat_id']}号" for item in rounds)
            + "）；同意票需严格超过有投票权存活玩家的一半方可处决"
            + ("，其中蕾雅决斗的两张牌达到半数即可处决。" if duel else "。"),
            alert=True,
        )
    if index == 0:
        plugins.emit(
            game, events, "phase_enter", {"from": "nomination", "to": "voting", "day": game["day"]}
        )


def close_vote(game, events):
    voters = eligible_voters(game)
    rounds = nomination_rounds(game)
    index = len(game["vote_rounds"])
    nominee = rounds[index]
    choices = {s["id"]: seat_choice(game, s["id"], nominee["card_id"]) for s in voters}
    require(all(choices.values()), "仍有玩家未投票，可先警告")
    yes = sum(choice == "yes" for choice in choices.values())
    # 分母在投票开始时冻结（见 state.vote_denominator）：即使中途有人整席出局，也不能让
    # 玩家表单上已经写明的门槛在计票这一刻变掉。
    n = vote_denominator(game)
    # 蕾雅决斗当天的两张牌门槛降为「恰好达到半数即可通过」：取 floor(n/2)（7 人局 3 票，
    # 与严格过半的 4 票才真正拉开差距）；其他候选仍严格过半；
    # 通知里的门槛必须与记录用同一个值。
    duel = nominee["card_id"] in duel_cards(game)
    # 防御性兜底：分母为 1 时 floor(n/2)＝0 会「0 票通过」，实战到不了（六个席位没有
    # 当前牌时 A、B 必然已整席出局、对局早就结束），但门槛至少是 1 票更稳妥。
    threshold = max(1, n // 2) if duel else n // 2 + 1
    tally = {
        "yes": yes,
        "denominator": n,
        "threshold": threshold,
        "duel": duel,
        "candidate": nominee["seat_id"],
        "excluded_puppets": (game.get("vote_freeze") or {}).get("excluded_puppets", 0),
    }
    plugins.emit(game, events, "vote_tally", tally)
    yes, n, threshold = tally["yes"], tally["denominator"], tally["threshold"]
    passed = yes >= threshold
    # 投票期间某人可能已经出局（主持人裁定、魔女希罗主动出局等）。轮次表为了不让索引
    # 错位不能中途删候选，但已经不在场的牌不能再被记成「通过处决」并公示一次。
    alive = bool(game["cards"][nominee["card_id"]]["alive"])
    record = {
        "candidate": nominee["seat_id"],
        "yes": yes,
        "denominator": n,
        "threshold": threshold,
        "passed": passed,
    }
    game["vote_rounds"].append(record)
    if passed and alive and nominee["card_id"] not in game["execution"]:
        game["execution"].append(nominee["card_id"])
    log_event(
        game,
        "vote",
        f"投票处决{nominee['seat_id']}号：同意{yes}/{n}，{'通过' if passed else '未通过'}",
    )
    if passed and not alive:
        outcome = "该牌已出局，不再处决"
    else:
        outcome = "通过处决" if passed else "未通过"
    notify(
        game,
        events,
        f"{nominee['seat_id']}号：同意{yes}/{n}，门槛{threshold}，{outcome}。",
        alert=True,
    )
    open_vote(game, events)


def advance(game, events):
    require(not game["pending"], "仍有待裁定事项，请先在「裁决」里逐项处理后再推进")
    game.pop("rewound_night", None)
    phase = game["phase"]
    if phase == "witch":
        convert_daily(game, events)
    elif phase in {"night", "night_coco"}:
        unlock_coco(game, events)
        lock_night(game, events)
    elif phase == "night_review":
        require(game["night"]["preview"] is not None, "尚无预结算结果")
        # 统一走 apply_damage：希罗缺阵时先回溯，再决定是否落死亡。
        apply_damage(game, events, game["night"]["preview"])
        if game.get("rewound_night"):
            return
        game["phase"] = "night_results"
        check_winner(game)
    elif phase == "night_results":
        require(
            not game["winner_candidate"],
            "本夜已有胜负候选，请先完成连锁并宣判，不能切换为白天后重新判定",
        )
        game["half"] = "day"
        game["phase"] = "speech"
        # 下层牌在第二天白天自动登场：公开头像改为当前牌，本人收到私密提示。
        for before in game["queued_reveals"]:
            s = seat(game, before["seat_id"])
            lower = current(game, s)
            if not lower:
                continue
            s["avatar_role_id"] = lower["role_id"]
            text = f"下层角色{ROLES[lower['role_id']]['name']}已登场。"
            if lower["id"] == "honoka":
                shown = honoka.apply_disguise(game, s)
                text += (
                    f"按先前选择示人为{ROLES[shown]['name']}。"
                    if shown
                    else "你可以选择一次示人角色。"
                )
            notify(game, events, text, [s["id"]], "下层登场")
        # 天亮只发一条汇总：逐条死讯与夜终总结合并，同一批死讯不再刷两遍。
        # 角色卡死亡卡片与这句话同一条消息：一夜多人都出局时合并成一张卡。
        queued_deaths = game.get("queued_deaths") or []
        if game["queued_notices"]:
            notify(
                game,
                events,
                f"第{game['day']}夜：" + "".join(game["queued_notices"]),
                alert=True,
                reference_title="夜终公告",
                # half 显式写成 night：这句话在天亮时说，但公布的是昨夜出局。
                payload=death_card_payload(game, queued_deaths, half="night")
                if queued_deaths
                else None,
            )
        else:
            notify(
                game, events, f"第{game['day']}夜是平安夜。", alert=True, reference_title="夜终公告"
            )
        # 夜间的被动技能播报也在这一刻补发（替死 / 爱人庇护 / 转爱自己）：
        # 死亡公告之前发会提前泄露夜里的结算，所以统一压到天亮。
        publish_night_passives(game, events)
        dead_first = [
            d["seat_id"] for d in game["deaths"] if d["day"] == game["day"] and d["half"] == "night"
        ]
        order = game["public"]["speech_order"] or speech_plan(game, dead_first)
        game["public"]["speech_order"] = order
        game["public"]["speaker"] = next_speaker(game, None, events)
        game["queued_notices"] = []
        game["queued_reveals"] = []
        game["queued_deaths"] = []
        game["nominations"] = []
        game["nomination_done"] = []
        game["ballots"] = {}
        game["vote_rounds"] = []
        game["execution"] = []
        for declaration in game["declarations"]:
            if declaration["status"] == "open":
                declaration["status"] = "complete"
        game["pending"] = [p for p in game["pending"] if not p.get("declaration_id")]
        sync_declarations(game)
    elif phase == "speech":
        # 兜底：状态若绕过 apply_command 变成「当前发言人无人可操作」，就地顺延，
        # 不要停在它身上；后面还有人可发言时下面的 require 仍会照常拒绝推进。
        sync_speaker(game, events)
        require(game["public"]["speaker"] is None, "仍有顺序发言未完成，请玩家确认或警告超时")
        game["phase"] = "discussion"
    elif phase == "discussion":
        game["phase"] = "nomination"
        game["discussion_end_requests"] = []
    elif phase == "nomination":
        require(not pending_nominators(game), "仍有玩家未提名或放弃，可警告后等待30秒")
        open_vote(game, events)
    elif phase == "voting":
        # 选票一次性提交全部候选，推进也一次结算全部候选：逐轮 close_vote 直到离开
        # 投票阶段，结果同一条命令里一起公布；某一轮缺票时照旧拒绝推进。
        while game["phase"] == "voting":
            close_vote(game, events)
    elif phase == "execution":
        awaiting = {
            owner(game, cid)["id"]
            for cid in game["execution"]
            if game["cards"][cid]["alive"]
            and cid == "nanoka"
            and role_card(game, cid)["uses"].get("bullets", 0) > 0
            # 傀儡当前牌在主人出局后无人可代开枪；排它会让处决永远推不动。
            and card_actionable(game, game["cards"][cid])
        }
        require(awaiting.issubset(game["execution_ready"]), "临刑开枪响应尚未确认，可先警告")
        attacks = [
            # 处决不吃庇护降级：进名单即出局，庇护与当夜 protect 都不能把它改成负伤。
            {
                "target_card": cid,
                "cause": "execution",
                "source_card": None,
                "unconditional": True,
            }
            for cid in game["execution"]
        ]
        attacks.extend(game.get("execution_shots", []))
        # 白天只有奈乃香的枪会替死：处决死亡因 cause=execution 被排除，命中枪可以被米莉亚顶掉。
        preview = resolve_intents(game, events, attacks)
        apply_damage(game, events, preview)
        if game.get("rewound_night"):
            return
        game["phase"] = "dusk"
    elif phase == "dusk":
        require(not game["winner_candidate"], "已有胜负候选，请确认本半天所有效果后宣判或裁定纠错")
        sherry.finish_day_binding(game, events)
        game["day"] += 1
        game["half"] = "night"
        game["phase"] = "witch"
        game["public"]["speaker"] = None
        # 打断标记属于当天：不清理会留到第二天的顺序发言里，把发言人拉回旧席位。
        game["public"].pop("interrupted_speaker", None)
        game["public"]["speech_order"] = []
        game["speech_passed"] = []
        game["speech_queued"] = {}
    else:
        raise GameError("当前阶段不能推进")
    if game.pop("rewound_night", False):
        # 本阶段内的预结算触发了希罗回溯：时间线已换掉，不得再写阶段/快照/日志。
        return
    # 夜间预结算/处决判死发生在本函数里：主人出局后傀儡当前牌要跟着当场出局
    # （见 sync_puppet_bonds）。
    meruru.sync_puppet_bonds(game, events)
    if game.pop("rewound_night", False):
        # 傀儡当前牌是希罗：这次即时出局又触发了一次回溯，同样不能再写阶段/快照。
        return
    game["warnings"] = {}
    game["deadline"] = None
    # 顺序发言的30秒倒计时随阶段进出：刚进入发言阶段就为第一位计时，离开即清除。
    sync_speech_timer(game)
    if game["phase"] != phase and game["phase"] in {
        "night_results",
        "speech",
        "discussion",
        "nomination",
        "dusk",
        "witch",
    }:
        plugins.emit(
            game, events, "phase_enter", {"from": phase, "to": game["phase"], "day": game["day"]}
        )
    save_snapshot(game)
    if game["status"] != "ended":
        # 阶段推进不再发系统消息：两端都有阶段标题与全屏阶段动画，只留主持人日志。
        log_event(game, "phase", f"对局进入第{game['day']}天 · {PHASES[game['phase']]}")


def execute_declaration(game, events, declaration):
    if declaration["executed"]:
        return
    data = declaration["data"]
    cid, ability = declaration["card_id"], declaration["ability"]
    card = game["cards"][cid]
    # 处决幻视自 2026-09-27 起是被动技能，不再有声明：名单定稿时由 auto_gaze 直接结算。
    # 效果类声明里只剩「赠送照片」仍吃中毒效果骰；其余真实声明不再因中毒被判假。
    if (
        ability in POISON_EFFECT_ABILITIES
        and not declaration["fake"]
        and not effect_effective(game, card, DAY_ABILITIES[ability][1])
    ):
        declaration["fake"] = True
        declaration["executed"] = True
        return
    if declaration["fake"] and ability in {"photo", "love"}:
        declaration["executed"] = True
        return
    target = data.get("target")
    target_card = current(game, target) if target else None
    if target:
        require(target_card is not None, "声明目标已不在场，请停止声明并重新裁定")
    module = next(
        module for module in plugins.enabled(game) if DAY_ABILITIES[ability][0] == module.ID
    )
    module.execute_declaration(game, events, declaration, target_card)
    declaration["executed"] = True


def revert_declaration(game, declaration):
    """质疑成功：只撤销这次声明已经生效的那部分效果，其他声明不受影响。"""
    effects = declaration.get("effects") or {}
    if "duel" in effects and (game.get("duel") or {}).get("leia_card") == effects["duel"]:
        game["duel"] = None
        game["duel_approvals"] = {}
    if (
        effects.get("interrupted_speaker")
        and game["public"].get("interrupted_speaker") == effects["interrupted_speaker"]
        and game["public"].get("speaker") == effects.get("speaker")
    ):
        game["public"]["speaker"] = game["public"].pop("interrupted_speaker")
    if "execution_card" in effects:
        cid = effects["execution_card"]
        seat_id = owner(game, cid)["id"]
        voted_out = any(
            record.get("passed") and record.get("candidate") == seat_id
            for record in game["vote_rounds"]
        )
        if not voted_out:
            game["execution"] = [item for item in game["execution"] if item != cid]
    if "penalty_seat" in effects:
        game["spiritual"]["annan_penalty"].pop(effects["penalty_seat"], None)
    if "self_execution_card" in effects:
        # 假洗脑被质疑成功：安安本人这一半（负面效果）还没执行，直接撤销。
        game["execution"] = [
            item for item in game["execution"] if item != effects["self_execution_card"]
        ]
        lock = game.get("execution_lock") or {}
        if effects.get("self_execution_card") in (lock.get("cards") or []):
            game["execution_lock"] = None


def resolve_pending(game, events, data):
    item = next(p for p in game["pending"] if p["id"] == data["pending_id"])
    kind = item["kind"]
    if kind == "information":
        notify(
            game, events, data["text"], [item["seat_id"]], "主持人裁定信息", item.get("image_id")
        )
    elif kind == "suspects":
        suspects = data.get("suspects") or []
        source = item.get("source_card") or data.get("true_source")
        shown_source = (
            game["cards"][source]["states"].get("display_killer", source) if source else None
        )
        if not item.get("truthful", True):
            # 目击信息骰失败时换掉入选的显示真凶；主持人已省略真凶的名单保持原样。
            suspects = false_witness(game, suspects, shown_source)
        honoka.queue_witness(game, events, item, suspects)
    elif kind == "evidence":
        if data.get("allow"):
            recipients = None if data.get("public") else data.get("recipients", [])
            require(recipients is None or recipients, "请选择公开或指定接收者")
            if item.get("text") or item.get("image_id"):
                # 公示正文默认是「N号留下遗物xxx」；主持人改过就用改过的，
                # 老客户端不带这个字段时仍按默认补全前缀。
                text = data.get("text") or evidence_public_text(item)
                notify(
                    game,
                    events,
                    text,
                    recipients,
                    "遗留证物",
                    item.get("image_id"),
                    reference_title="遗留证物" if recipients is None else None,
                )
    elif kind == "codex":
        if data["outcome"] == "convert":
            require(data.get("target") in game["cards"], "请选择特殊转化目标")
            set_witch(game, events, data["target"])
        begin_night(game, events)
    elif kind == "madness":
        if data["outcome"] == "penalty":
            cid = data["target"]
            effect = data["penalty"]
            require(effect != "none" or bool(data["reason"].strip()), "请明确不利裁定")
            if effect == "death":
                apply_damage(
                    game,
                    events,
                    resolve_intents(
                        game,
                        events,
                        [{"target_card": cid, "cause": "madness", "unconditional": True}],
                        substitute=False,
                    ),
                )
            elif effect == "poison":
                game["cards"][cid]["states"]["poisoned"] = True
            elif effect == "lose":
                game["spiritual"]["personal_losses"].extend(
                    audience(game, [owner(game, cid)["id"]])
                )
        notify(game, events, data["reason"], [item["seat_id"]], "疯狂行为裁定")
    game["pending"] = [p for p in game["pending"] if p["id"] != item["id"]]


def sync_declarations(game):
    def summary(declaration):
        data = declaration["data"]
        if data.get("target"):
            return f"目标：{data['target']}号"
        if data.get("participants"):
            return "参与席位：" + "、".join(f"{sid}号" for sid in data["participants"])
        return "无目标"

    game["public"]["declarations"] = [
        {
            "id": declaration["id"],
            "seat_id": declaration["seat_id"],
            "label": DAY_ABILITIES[declaration["ability"]][1],
            "summary": summary(declaration),
            "status": declaration["status"],
        }
        for declaration in game["declarations"]
        if declaration["day"] == game["day"]
    ]


def skill_broadcast_payload(game, declaration):
    """白天技能声明的结构化播报：技能名、介绍、使用者与目标。

    载荷里带的是完整真相（包括伪装声明与私密目标），下发时由
    :func:`backend.app.storage.project_message_payload` 按收件人裁剪：
    目标是公开信息（打断、决斗、全场洗脑）或收件人就是声明者/主持人时才给目标；
    ``fake`` 与牌 id 只给主持人——伪装声明在其他人眼里必须与真声明完全一致。
    """
    ability = declaration["ability"]
    sid = declaration["seat_id"]
    role_id = DAY_ABILITIES[ability][0]
    target = declaration["data"].get("target")
    seat = next((s for s in game["seats"] if s["id"] == sid), None)
    target_seat = (
        next((s for s in game["seats"] if s["id"] == str(target)), None) if target else None
    )
    return {
        "type": "skill",
        "declaration_id": declaration["id"],
        "ability": ability,
        "ability_name": ABILITY_NAMES.get(ability, DAY_ABILITIES[ability][1]),
        "role_id": role_id,
        "role_name": ROLES.get(role_id, {}).get("name", role_id),
        "intro": ABILITY_INTRO.get(ability, ""),
        "seat_id": sid,
        "actor_participant_id": (seat or {}).get("occupant_id"),
        "_animation": skill_animation_snapshot(
            role_id,
            ability,
            ABILITY_NAMES.get(ability, DAY_ABILITIES[ability][1]),
            game["cards"][declaration["card_id"]]["witch"],
        ),
        "actor_name": display_player_name((seat or {}).get("name", "")),
        "challengeable": challengeable(game, declaration),
        "target_public": ability in PUBLIC_TARGET_ABILITIES,
        "target": (
            {
                "seat_id": target_seat["id"],
                "name": display_player_name(target_seat["name"]),
            }
            if target_seat
            else None
        ),
        # 以下两项只对主持人下发。
        "fake": bool(declaration.get("fake")),
        "card_id": declaration["card_id"],
    }


def host_command(game, events, action, data):
    if action == "host.start":
        require(game["status"] == "lobby" and game["phase"] == "ordering", "请先全员准备并发牌")
        require(
            all(s["occupant_id"] and s["ready"] for s in game["seats"]),
            "需要7名玩家全部入座、确认上下牌并准备",
        )
        for s in game["seats"]:
            s["avatar_role_id"] = current(game, s)["role_id"]
        honoka_seat = owner(game, "honoka")
        # 未登场的穗乃香保留已选的示人角色，等她登场时再自动套用（见 state.apply_honoka_disguise）。
        honoka.apply_disguise(game, honoka_seat)
        game["status"] = "playing"
        game["phase"] = "witch"
        sherry.start_binding(game, events)
        sid = honoka_seat["id"]
        # 穗乃香的「开局前获知上层牌」是普通技能，不吃中毒/信息骰：这里恒发真表。
        # 与排序阶段预览（views.game_view 的 honoka_upper）同源，不许出现假值分支。
        upper = [(s["id"], current(game, s)["role_id"]) for s in game["seats"] if s["id"] != sid]
        notify(
            game,
            events,
            "；".join(f"{seat_id}号：{ROLES[role]['name']}" for seat_id, role in upper),
            [sid],
            "开局上层角色",
        )
        plugins.emit(game, events, "game_started", {"day": game["day"]})
        plugins.emit(
            game, events, "phase_enter", {"from": "ordering", "to": "witch", "day": game["day"]}
        )
        save_snapshot(game)
        notify(game, events, "所有上下牌已锁定，对局开始。")
        for module in plugins.enabled(game):
            detail = plugins.info(module)
            notify(
                game,
                events,
                f"本局规则：{detail['name']} v{detail['version']}\n{detail['description']}",
                alert=True,
                payload={"type": "plugin", **detail},
            )
    elif action == "host.advance":
        force_advance(game, events)
    elif action == "host.auto":
        paused = not game["public"].get("auto_advance_off")
        game["public"]["auto_advance_off"] = paused
        notify(
            game,
            events,
            "已暂停自动推进，本阶段改由主持人手动推进。"
            if paused
            else "已恢复自动推进，无人待办时 5 秒后自动进入下一阶段。",
        )
    elif action == "host.hanna_witch":
        require(hanna_witch_window(game), "「汉娜魔化」只能在第三天入夜前调整")
        value = data["value"] == "on"
        if bool(game.get("hanna_witch")) != value:
            game["hanna_witch"] = value
            notify(
                game,
                events,
                "已开启「汉娜魔化」：第三天夜里满足条件时由汉娜覆盖当天魔女人选。"
                if value
                else "已关闭「汉娜魔化」：第三天夜按艾玛与魔女阵营的常规人选结算。",
                [],
                "规则调整",
            )
    elif action == "host.resolve":
        resolve_pending(game, events, data)
    elif action == "host.codex":
        roles = list(data["roles"])
        SystemRandom().shuffle(roles)
        game["codex"] = roles
    elif action == "host.codex_order":
        game["codex"] = list(data["roles"])
        notify(game, events, data["reason"], [], "魔典裁定")
    elif action == "host.speech":
        # 仅发言阶段可调整：提前预设会整体旁路死者优先、魔女化更早的自动排序。
        require(game["phase"] == "speech", "进入顺序发言阶段后才能调整发言顺序")
        ids = [s["id"] for s in living(game) if seat_operable(game, s["id"])]
        require(data["start"] in ids, "只能从有人可操作的存活席位开始")
        index = ids.index(data["start"])
        order = ids[index:] + ids[:index]
        if data["direction"] == "desc":
            order = [order[0]] + order[1:][::-1]
        game["public"]["speech_order"] = order
        game["public"].pop("interrupted_speaker", None)
        notify(game, events, "发言顺序：" + " → ".join(order))
        game["public"]["speaker"] = next_speaker(game, None, events)
    elif action == "host.warn":
        outstanding = outstanding_seats(game)
        if data.get("all"):
            targets = outstanding
        else:
            targets = [data["seat_id"]] if data.get("seat_id") else []
        require(
            targets and all(sid in outstanding for sid in targets),
            "该席位当前没有可超时的待确认操作",
        )
        for sid in targets:
            game["warnings"][sid] = clock.now() + 30
        game["deadline"] = min(game["warnings"].values())
        if len(targets) > 1:
            notify(
                game,
                events,
                "已警告下列席位："
                + "、".join(f"{sid}号" for sid in targets)
                + "，请在30秒内完成操作。",
                targets,
                "主持人警告",
            )
        else:
            notify(
                game,
                events,
                f"已警告{targets[0]}号玩家：请在30秒内完成操作。",
                targets,
                "主持人警告",
            )
    elif action == "host.water":
        require(
            game["half"] == "night" and game["phase"] in {"night", "night_coco", "night_review"},
            "13水只在夜间行动、最后夜间行动或主持人预结算阶段发放",
        )
        holders = game["water"]["holders"]
        require(data["seat_id"] not in holders, "该席位本夜已经持有13水")
        require(current(game, data["seat_id"]), "只能把13水发给仍有当前牌的席位")
        holders.append(data["seat_id"])
        notify(
            game,
            events,
            "你获得一瓶13水，本次使用无需主持人确认；本夜结束时未使用会过期收回。",
            [data["seat_id"]],
            "13水",
        )
    elif action == "host.damage":
        attacks = [
            {
                "target_card": cid,
                "source_card": data.get("source") or None,
                "cause": "host",
                "unconditional": data["effect"] == "unconditional",
                "injury": data["effect"] == "injury",
                "allow_lower": True,
            }
            for cid in data["targets"]
        ]
        if game["half"] == "night" and game["phase"] in {"night", "night_coco", "night_review"}:
            game["night"].setdefault("extra_attacks", []).extend(attacks)
            if game["night"]["locked"]:
                prepare_night_preview(game, events)
        else:
            apply_damage(game, events, resolve_intents(game, events, attacks, substitute=False))
        notify(game, events, data["reason"], [], "伤害裁定")
    elif action == "host.state":
        cid, state, value = data["card_id"], data["state"], data.get("value", False)
        card = game["cards"][cid]
        if state == "witch":
            if value and not card["witch"]:
                set_witch(game, events, cid)
            elif not value:
                card["witch"] = False
        elif state == "alive":
            require(
                game["phase"] not in {"night", "night_coco", "night_review"},
                "未公布夜间结算时请使用伤害预结算入口，避免泄露死讯",
            )
            if value and not card["alive"]:
                revive(game, events, cid)
            elif not value and card["alive"]:
                apply_damage(
                    game,
                    events,
                    resolve_intents(
                        game,
                        events,
                        [
                            {
                                "target_card": cid,
                                "cause": "host",
                                "unconditional": True,
                                "allow_lower": True,
                            }
                        ],
                        substitute=False,
                    ),
                )
        elif state == "injured":
            card["injured"] = value
        elif state == "protected":
            # 庇护按天记账：开启时写日戳，到次日夜里自动过期（见 state.protection_active）。
            if value:
                card["states"]["protected_day"] = game["day"]
            else:
                card["states"].pop("protected_day", None)
            if data.get("persistent"):
                game["spiritual"]["persistent_states"].setdefault(cid, {})["protected_day"] = card[
                    "states"
                ].get("protected_day")
        else:
            if state == "puppet":
                require(not value or data.get("master"), "傀儡需指定主人")
                value = data["master"] if value else None
                if value:
                    # 傀儡与「无技能」必须成对：少了 no_ability 就变成会发动技能的怪物，
                    # 多了它又会在解除之后永久废掉一张牌（release_puppet 一起清）。
                    card["states"]["puppet"] = value
                    card["states"]["no_ability"] = True
                else:
                    release_puppet(card)
            else:
                card["states"][state] = value
            if data.get("persistent"):
                kept = game["spiritual"]["persistent_states"].setdefault(cid, {})
                # 傀儡的持久化要连 no_ability 一起写：回溯只回放这里记下的键，
                # 少了它就会复活出一个「有主人但会发动技能」的傀儡。
                kept.update(
                    {"puppet": value, "no_ability": bool(value)}
                    if state == "puppet"
                    else {state: value}
                )
            # 傀儡化或失去技能会立刻改变本夜谁能行动，必须同步已确认集合，
            # 否则该席既拿不到行动又留下阻塞的主持人待办。
            sync_night_confirmations(game, events)
        check_winner(game)
        notify(
            game,
            events,
            data["reason"],
            None if data.get("public") else [owner(game, cid)["id"]],
            "主持人状态裁定",
            reference_title="主持人状态裁定" if data.get("public") else None,
        )
        if game["phase"] == "night_review":
            prepare_night_preview(game, events)
    elif action == "host.information":
        recipients = None if data.get("public") else data.get("recipients", [])
        require(recipients is None or recipients, "请选择公开或指定接收者")
        require(data.get("text") or data.get("image_id"), "信息需要正文或图像")
        notify(
            game,
            events,
            data.get("text", ""),
            recipients,
            data["title"],
            data.get("image_id"),
            reference_title="主持人公开信息" if recipients is None else None,
        )
    elif action == "host.madness":
        pending(game, "madness", data["reason"], seat_id=data["seat_id"])
    elif action == "host.rewind":
        rewind(game, data["snapshot"], events, keep_states=data.get("keep_states", []))
    elif action == "host.confirm_winner":
        require(data["confirm"] and not game["pending"], "请先处理全部连锁裁定并确认")
        check_winner(game)
        require(game["winner_candidate"], "当前尚未达到胜利条件")
        finish(game, events, **game["winner_candidate"])
    elif action == "host.surrender":
        side = data["side"]
        if side == "witch":
            # 「只剩可可一名魔女」按**场上**的魔女牌算：已经魔女化但还没登场的下层牌
            # 不该让魔女交牌被误拒。同意只看今天，且必须是可可本人的申请。
            witches = [c for c in game["cards"].values() if c["witch"] and present(game, c["id"])]
            require(
                len(witches) == 1
                and witches[0]["id"] == "coco"
                and surrendered_today(game, owner(game, "coco")["id"]),
                "仅剩可可一名魔女且本人申请时，魔女才能交牌",
            )
        else:
            # 好人席位按**开局抽定的魔女阵营**判定，不是按某张牌有没有魔女化：
            # 命运席位 A、B 的另一张牌本来就不是魔女，用「有没有非魔女牌」会把两个
            # 敌方席位算成好人，而那两个玩家永远不会同意，交牌条件因此恒不可达。
            # 整席出局的席位拿不到交牌按钮、也不能再替阵营表态，一律不计入。
            faction = set(witch_faction(game))
            good_seats = [
                s["id"]
                for s in game["seats"]
                if s["id"] not in faction and current(game, s) is not None
            ]
            require(
                all(surrendered_today(game, sid) for sid in good_seats),
                "需要所有好人分别私信同意交牌",
            )
            require(game["generated_witches"], "尚未生成魔女，需主持人特殊胜负裁定")
            for s in game["seats"]:
                if not any(cid in game["generated_witches"] for cid in s["cards"]):
                    game["spiritual"]["personal_losses"].extend(audience(game, [s["id"]]))
        finish(game, events, "good" if side == "witch" else "witch", data["reason"])
    elif action == "host.end":
        finish(game, events, data["winner"], data["reason"])


# 警告只对“当前阶段卡住的这个行动”有效，提前做别的事不算完成本阶段。
PHASE_ACTIONS = {
    "night": {"night.confirm"},
    "night_coco": {"night.confirm"},
    "speech": {"speech.done", "speech.speak"},
    "nomination": {"vote.nominate", "vote.pass"},
    "voting": {"vote.cast"},
    "execution": {"execution.shoot", "execution.confirm"},
}


def player_command(game, actor, events, action, data, *, by_host=False):
    s = player_seat(game, actor)
    sid = s["id"]
    card = current(game, s)
    phase = game["phase"]
    if action == "lobby.order":
        require(game["status"] == "lobby" and game["phase"] == "ordering", "发牌后才能调整上下牌")
        require(not s["ready"], "下层牌已确定，不能再改上层角色")
        top_role = game["cards"][data["top"]]["role_id"]
        require(top_role not in DEAL_LOWER_ROLES, "艾玛、米莉亚、亚里沙必须放在下层")
        s["cards"] = [data["top"]] + [cid for cid in s["cards"] if cid != data["top"]]
        s["ready"] = False
    elif action == "lobby.ready":
        require(game["status"] == "lobby" and game["phase"] in {"lobby", "ordering"})
        s["ready"] = True if game["phase"] == "ordering" else not s["ready"]
        if game["phase"] == "lobby" and all(
            other["occupant_id"] and other["ready"] for other in game["seats"]
        ):
            deal_cards(game)
            notify(game, events, "全员首次准备完成，已私下发牌；请调整上下牌并再次准备。")
            for s in game["seats"]:
                # A、B 说清当值日，艾玛席只给条件式预告，其余席位只回答前三天。
                notify(
                    game,
                    events,
                    witch_destiny_notice(game, s["id"]),
                    [s["id"]],
                    "魔女化命运",
                )
            plugins.emit(
                game, events, "phase_enter", {"from": "lobby", "to": "ordering", "day": game["day"]}
            )
    elif action == "player.profile":
        require(1 <= len(data["name"].strip()) <= 30, "公开称呼需为1至30字")
        s["name"] = data["name"].strip()
    elif action == "night.submit":
        ability = data["ability"]
        cid = game["night"]["actors"][sid]
        card = game["cards"][cid]
        # 本夜能用的行动必须在这张牌的技能表里：傀儡只剩魔女刀（13 水不走这里），
        # 失去技能/被傀儡化的牌不会出现在行动表上，这里再挡一道。主持人代操作
        # （by_host）不受限，那是纠错通道。
        require(
            by_host or ability in night_abilities(game, card),
            "傀儡与失去技能的角色不能发动技能",
        )
        target = current(game, data["target"]) if data.get("target") else None
        if target:
            require(target_allowed(game, target["id"]), "本夜所有目标必须符合注视范围")
        entry = {
            "id": uid(),
            "seat_id": sid,
            "participant_id": actor["id"],
            "card_id": cid,
            "ability": ability,
            "confirmed": False,
            "by_host": by_host,
            "title": f"{sid}号夜间选择",
            **deepcopy({k: v for k, v in data.items() if k != "ability"}),
        }
        if ability == "swap":
            millia.record_swap(game, data.get("target"))
        if target:
            entry["target_seat"], entry["target_card"] = data["target"], target["id"]
        game["night"]["actions"] = [
            a
            for a in game["night"]["actions"]
            if not (a["seat_id"] == sid and a["ability"] == ability)
        ] + [entry]
    elif action == "night.clear":
        clear_seat_actions(game, sid, events)
    elif action == "night.confirm":
        actions = [a for a in game["night"]["actions"] if a["seat_id"] == sid]
        card = game["cards"][game["night"]["actors"][sid]]
        if card["id"] == "hiro" and card["witch"]:
            hiro.confirm_madness(game, card, actions, sid)
        if card["id"] == "emma" and card["witch"]:
            # 魔女化艾玛必须杀光全场，不能「放弃并确认」。
            require(
                any(a["ability"] == "massacre" for a in actions),
                "魔女化艾玛必须提交全场攻击",
            )
        if card["id"] == "millia":
            millia.require_swap(game, sid, actions)
        for selected in actions:
            selected["confirmed"] = True
        game["night"]["confirmed"].append(sid)
        unlock_coco(game, events)
    elif action == "day.skill":
        ability = data["ability"]
        # 傀儡与失去技能的角色不能发动白天技能（含伪装声明）：行动表里已经不给入口，
        # 这里再挡一道，避免绕过表单直接提交。
        require(
            by_host or can_use_ability(game, card, bool(actor.get("puppet_controlled"))),
            "傀儡与失去技能的角色不能发动技能",
        )
        use_card = card
        if data.get("card_id") and data["card_id"] != (card["id"] if card else None):
            candidate = game["cards"].get(data["card_id"])
            # 新版规则：艾玛即使在下层也可打断一次发言。
            require(
                candidate
                and candidate["role_id"] == "emma"
                and ability == "interrupt"
                and candidate["alive"]
                and owner(game, candidate["id"])["id"] == sid,
                "此时不能用该角色牌声明技能",
            )
            use_card = candidate
        require(use_card is not None, "当前没有可声明技能的角色牌")
        require(
            ability not in debunked_abilities(game, sid),
            "该技能已被质疑拆穿，本局不能再发动",
        )
        real = can_day_ability(game, use_card, ability)
        fake = not real and day_fake_allowed(game, use_card, ability)
        require(real or fake, "此时不能声明该技能")
        declaration = {
            "id": uid(),
            "day": game["day"],
            "seat_id": sid,
            "card_id": use_card["id"],
            "ability": ability,
            "fake": fake,
            "by_host": by_host,
            "data": deepcopy(data),
            "status": "open",
            "executed": False,
        }
        game["declarations"].append(declaration)
        execute_declaration(game, events, declaration)
        if real and declaration["executed"] and not declaration["fake"]:
            plugins.emit(
                game,
                events,
                "day_declaration",
                {
                    "declaration_id": declaration["id"],
                    "card_id": use_card["id"],
                    "ability": ability,
                },
            )
        sync_declarations(game)
        # Publish a changed speaking turn first, so its intro cannot replace the skill cut-in.
        sync_speaker(game, events)
        suffix = "该技能不可质疑。" if ability in {"photo", "love", "gaze"} else "其他玩家可质疑。"
        # 文本与结构化载荷共同保留在历史；按收件人的裁剪在 storage.message_view 完成。
        notify(
            game,
            events,
            f"{sid}号声明发动「{DAY_ABILITIES[ability][1]}」，{suffix}",
            alert=True,
            payload=skill_broadcast_payload(game, declaration),
        )
    elif action == "day.challenge":
        # 质疑与「白天技能声明」同一时窗：处决名单一旦进入结算（execution/dusk），
        # 已经定稿的结果不再接受质疑改写。
        require(game["phase"] in CHALLENGE_PHASES, "当前阶段不能再质疑")
        require(card, "已整席出局，不能质疑")
        d = next(d for d in game["declarations"] if d["id"] == data["declaration_id"])
        require(d["status"] == "open", "该技能声明已结束")
        require(d["seat_id"] != sid, "不可质疑自己")
        if d["ability"] == "interrupt":
            # 真艾玛不能质疑假艾玛（2026-09-27 作者原话：只有艾玛本人不能质疑）。
            require(owner(game, "emma")["id"] != sid, "艾玛不能质疑其他玩家发动的艾玛技能")
        require(challengeable(game, d), "该技能不能质疑")
        require(not lost_by_challenge(game, s), "质疑失败后不能再质疑")
        if d["fake"]:
            d["status"] = "stopped"
            # 只撤销这次声明自己已经生效的那部分效果，其他声明与已通过的投票不受影响。
            revert_declaration(game, d)
            for seat_id, penalty in list(game["spiritual"]["annan_penalty"].items()):
                if isinstance(penalty, dict) and penalty.get("declaration_id") == d["id"]:
                    del game["spiritual"]["annan_penalty"][seat_id]
            notify(
                game,
                events,
                f"{sid}号质疑成功：这次伪装技能已经生效的部分一并撤销，"
                f"{d['seat_id']}号的「{DAY_ABILITIES[d['ability']][1]}」本局不能再发动。",
                alert=True,
            )
        else:
            if s["occupant_id"] not in game["spiritual"]["personal_losses"]:
                game["spiritual"]["personal_losses"].append(s["occupant_id"])
            eliminate_seat(
                game,
                events,
                s,
                f"{sid}号质疑失败，两张角色牌直接出局，本局个人判负。",
            )
        sync_declarations(game)
    elif action == "speech.done":
        if sid == game["public"]["speaker"]:
            speech_done(game, events)
        else:
            require(sid in game["public"]["speech_order"], "你不在本次发言顺序里")
            require(sid not in game.get("speech_passed", []), "你已经处理过本次发言")
            # 预提交「本轮不发言」不再发系统消息：轮到时自动跳过即可。
            game.setdefault("speech_passed", []).append(sid)
    elif action == "speech.speak":
        # 只服务「还没轮到自己」的席位：当前发言人的「提前写发言」入口已经下线
        # （行动表里没有这个动作，validate_command 先一步拒绝），本人直接写在公屏再点
        # 「结束本次发言」即可；已经讲完的席位则在 speech_done 时就记进了 speech_passed。
        require(sid in game["public"]["speech_order"], "你不在本次发言顺序里")
        require(sid not in game.get("speech_passed", []), "你已经处理过本次发言")
        require(sid != game["public"]["speaker"], "轮到你时请直接在公屏发言")
        text = data["text"].strip()
        require(text, "请先写下发言内容")
        # 提前写好发言不再发系统消息，轮到时自动以本人身份公开。
        game.setdefault("speech_queued", {})[sid] = text
        game.setdefault("speech_passed", []).append(sid)
    elif action == "discussion.request_end":
        require(game["phase"] == "discussion", "当前不在自由发言阶段")
        require(card_actionable(game, card), "当前角色不能行动")
        requests = game.setdefault("discussion_end_requests", [])
        require(sid not in requests, "你已经提交过结束请求")
        # 进度由两端的「结束自由发言」进度条显示，不再逐人发系统消息。
        requests.append(sid)
    elif action == "vote.nominate":
        target = current(game, data["target"])
        require(target is not None, "该席位已经没有登场的角色牌，不能提名")
        game["nominations"].append({"seat_id": data["target"], "card_id": target["id"], "by": sid})
        game["public"]["nominations"] = [
            {"seat_id": n["seat_id"], "by": n["by"]} for n in game["nominations"]
        ]
        if game["phase"] == "voting":
            # 投票中新增的提名多出一个候选：立刻刷新候选表，让还没提交的人
            # 连同新候选一起补齐选票，已提交的部分不受影响。
            rounds = nomination_rounds(game)
            game["public"]["votes"]["candidates"] = [
                {"seat_id": item["seat_id"], "card_id": item["card_id"]} for item in rounds
            ]
            game["public"]["votes"]["total"] = len(rounds)
        notify(game, events, f"{sid}号提名{data['target']}号。")
        game.setdefault("nomination_done", []).append(sid)
    elif action == "vote.pass":
        # 放弃提名不再发系统消息：提名阶段的进度在顶部显示，提交完自动推进。
        game.setdefault("nomination_done", []).append(sid)
    elif action == "vote.cast":
        require(game["phase"] == "voting", "当前不在投票阶段")
        require(
            any(s["id"] == sid for s in eligible_voters(game)),
            "你没有投票权，不能投票",
        )
        rounds = {item["card_id"]: item for item in nomination_rounds(game)}
        cast = {}
        for card_id, choice in data.items():
            require(card_id in rounds, "候选已变化，请刷新后重新投票")
            require(choice in {"yes", "no", "abstain"}, "选票无效")
            if (
                choice == "yes"
                and card_id == "hanna"
                and game["spiritual"]["sherry_bound"]
                and card["id"] == "sherry"
            ):
                require(False, "雪莉不能同意处决绑定的汉娜")
            cast[card_id] = choice
        require(bool(cast), "没有需要提交的选票")
        # 决斗当天每个人必须至少同意两张决斗牌之一：一次表单没有先后顺序，
        # 因此把要求放在提交时校验；雪莉对汉娜的限制优先豁免（duel_vote_required）。
        duel = duel_cards(game)
        if len(duel) == 2 and duel_vote_required(game, sid):
            require(
                any(cast.get(cid) == "yes" for cid in duel),
                "今天必须至少同意蕾雅或决斗对象之一",
            )
        game.setdefault("ballots", {}).setdefault(sid, {}).update(cast)
        if any(cast.get(cid) == "yes" for cid in duel):
            game["duel_approvals"][sid] = True
    elif action == "execution.shoot":
        nanoka.shoot(game, actor, events, data, by_host=by_host)
    elif action == "execution.confirm":
        game["execution_ready"].append(sid)
    elif action == "photo.permission":
        photo = next(p for p in game["photos"] if p["id"] == data["photo_id"])
        photo["allowed"] = bool(data.get("allow"))
        notify(
            game,
            events,
            f"{sid}号{'允许' if photo['allowed'] else '不再允许'}你查看其后续夜间行动。",
            [photo["sender"]],
            "照片授权",
        )
    elif action == "water.use":
        target = current(game, data["target"])
        require(target is not None, "目标当前没有登场角色牌")
        require(
            game["half"] == "night" and game["phase"] in {"night", "night_coco", "night_review"},
            "13水只能在本夜行动期使用",
        )
        require(sid in game["water"]["holders"], "你本夜没有可用的13水")
        game["water"]["holders"].remove(sid)
        attack = {
            "target_card": target["id"],
            "source_card": card["id"] if card else None,
            "cause": "water",
            "hide_cause": bool(
                data.get("hide_cause") and card and card["id"] == "meruru" and card["witch"]
            ),
        }
        game["night"].setdefault("extra_attacks", []).append(attack)
        if game["night"]["locked"]:
            # 已锁夜：重算预结算，不创建主持人待办。
            prepare_night_preview(game, events)
        notify(game, events, f"{sid}号使用13水指定{data['target']}号。")
    elif action == "evidence.submit":
        dead = game["cards"][data["card_id"]]
        require(not dead["alive"], "只有已经出局的牌可以留下证物")
        require(data.get("text") or data.get("image_id"), "至少填写证物或上传图像")
        dead["states"]["evidence_used"] = True
        pending(
            game,
            "evidence",
            f"{sid}号遗留证物：裁定内容与公开范围",
            seat_id=sid,
            text=data.get("text", ""),
            image_id=data.get("image_id"),
        )
    elif action == "player.surrender":
        if not surrendered_today(game, sid):
            game["surrenders"].append({"seat": sid, "day": game["day"]})
        notify(game, events, "交牌意向已私信主持人；未满足集体条件前继续游戏。", [sid], "交牌申请")
    if sid in game["warnings"] and action in PHASE_ACTIONS.get(phase, ()):
        del game["warnings"][sid]
        game["deadline"] = min(game["warnings"].values(), default=None)


# 容易刷屏的操作不进日志：准备/发言/投票逐项提交、私信与常规聊天。
_LOG_SKIP = {
    "lobby.ready",
    "lobby.order",
    "night.clear",
    "speech.done",
    "speech.speak",
    "vote.cast",
    "vote.pass",
    "photo.permission",
    "player.profile",
    "host.warn",
    "host.auto",
    "host.codex",
    "host.codex_order",
    "host.speech",
}


def _ability_label(ability):
    if ability in DAY_ABILITIES:
        return DAY_ABILITIES[ability][1]
    if ability in NIGHT_ABILITIES:
        return NIGHT_ABILITIES[ability][1]
    return ability


def _target_text(game, data):
    target = (
        data.get("target")
        or data.get("target_card")
        or data.get("target_seat")
        or data.get("seat_id")
    )
    if not target:
        return ""
    target = str(target)
    try:
        seat(game, target)
        return f" → {target}号"
    except GameError:
        return f" → {ROLES.get(target, {}).get('name', target)}"


def _role_name(game, card_id):
    return ROLES.get(card_id, {}).get("name", card_id)


def command_log_text(game, actor, action, data, *, by_host=False):
    """把一次操作格式化成一行主持人日志；返回 None 表示此操作不记录。"""
    if action in _LOG_SKIP or action.startswith(("channel.", "room.")):
        return None
    who = "主持人" if actor["kind"] == "host" else f"{actor.get('seat_id', '?')}号"
    if by_host:
        who += "（代操作）"
    seat_id = actor.get("seat_id")
    name = None
    if seat_id and actor["kind"] == "player":
        raw = game["seats"][int(seat_id) - 1]["name"]
        # 默认称呼就是「N号玩家」时不再重复拼接，只有改过名的才带名字。
        if raw and raw != f"{seat_id}号玩家":
            name = display_player_name(raw)
    prefix = f"{who}玩家【{name}】" if name else who

    if action == "night.submit":
        ability = data.get("ability", "")
        return f"{prefix}使用{_ability_label(ability)}{_target_text(game, data)}"
    if action == "day.skill":
        ability = data.get("ability", "")
        return f"{prefix}声明白天技能「{_ability_label(ability)}」{_target_text(game, data)}"
    if action == "day.challenge":
        return f"{prefix}发起质疑"
    if action == "vote.nominate":
        return f"{prefix}提名{_target_text(game, data).lstrip(' →')}号"
    if action == "execution.shoot":
        return f"{prefix}临刑开枪"
    if action == "night.confirm":
        return f"{prefix}确认夜间行动"
    if action == "execution.confirm":
        return f"{prefix}处决前响应已确认"
    if action == "honoka.disguise":
        return f"{prefix}示人为{_role_name(game, data.get('role', ''))}"
    if action == "honoka.witness":
        return f"{prefix}设定目击显示身份为{_role_name(game, data.get('role', ''))}"
    if action == "hiro.exit":
        return f"{prefix}主动出局"
    if action == "water.use":
        return f"{prefix}使用13水{_target_text(game, data)}"
    if action == "meruru.revive":
        return f"{prefix}使用复活"
    if action == "evidence.submit":
        return f"{prefix}提交证物"
    if action == "player.surrender":
        return f"{prefix}申请交牌"
    if action == "host.start":
        return "主持人开局，上下牌锁定"
    if action == "host.advance":
        return None  # 阶段推进由 advance() 自己记录，避免重复行
    if action == "host.resolve":
        return None  # 裁定内容由各 resolve 分支单独记录
    if action == "host.hanna_witch":
        return f"主持人{'开启' if data.get('value') == 'on' else '关闭'}「汉娜魔化」"
    if action == "host.water":
        return f"主持人调整13水持有者为{data.get('seat_id', '?')}号"
    if action == "host.damage":
        return "主持人裁定伤害预结算"
    if action == "host.state":
        cid = data.get("card_id", "")
        return f"主持人修改{_role_name(game, cid)}状态 {data.get('state', '')}={data.get('value', False)}"
    if action == "host.information":
        return f"主持人发布信息「{data.get('title', '')}」"
    if action == "host.madness":
        return f"主持人裁定疯狂：{data.get('reason', '')}"
    if action == "host.rewind":
        return "主持人手动回溯时间"
    if action == "host.confirm_winner":
        return "主持人确认宣判胜负"
    if action == "host.surrender":
        return f"主持人处理交牌：{data.get('side', '')}方"
    if action == "host.end":
        return "主持人终止对局"
    return f"{prefix}执行 {action}"


def apply_command(game, actor, action, payload, *, by_host=False):
    require(game["status"] != "ended", "对局已结束，不能再操作")
    events = []
    validate_command(game, actor, action, payload)
    module = next((module for module in plugins.enabled(game) if action in module.COMMANDS), None)
    if module:
        require(action.startswith(module.ID + "."), "规则模块命令 ID 无效")
        module.COMMANDS[action](game, actor, events, payload, by_host=by_host)
    elif actor["kind"] == "host":
        host_command(game, events, action, payload)
    else:
        player_command(game, actor, events, action, payload, by_host=by_host)
    line = command_log_text(game, actor, action, payload, by_host=by_host)
    if line is not None:
        kind = "host" if actor["kind"] == "host" else "action"
        log_event(game, kind, line)
    if by_host and actor["kind"] == "player":
        notify(
            game,
            events,
            f"主持人为{actor['seat_id']}号完成了本阶段操作（内容不公开）。",
            seats=[actor["seat_id"]],
        )
    # 这条命令可能杀掉了主人：傀儡当前牌跟着出局（见 sync_puppet_bonds）。
    meruru.sync_puppet_bonds(game, events)
    sync_speaker(game, events)
    sync_auto_advance(game)
    game["version"] += 1
    return events


def discussion_end_ready(game):
    """自由发言：在场不足六人时全员提交结束请求后即可自动推进。"""
    return (
        game["status"] == "playing"
        and game["phase"] == "discussion"
        and not game["pending"]
        and discussion_end_reached(game)
    )


def auto_advance_ready(game):
    """玩家行动完即可推进的阶段由系统计时，主持人只需处理待裁定事项。"""
    return (
        game["status"] == "playing"
        and game["phase"] in AUTO_PHASES
        and not game["pending"]
        and not game["public"].get("auto_advance_off")
        and not outstanding_seats(game)
    )


def sync_auto_advance(game):
    """没人在等的时候开始倒计时；自由发言结束请求用 10 秒，其余阶段 5 秒。"""
    if discussion_end_ready(game):
        game["public"].setdefault("auto_advance_at", clock.now() + DISCUSSION_END_DELAY)
    elif auto_advance_ready(game):
        game["public"].setdefault("auto_advance_at", clock.now() + AUTO_ADVANCE_DELAY)
    else:
        game["public"].pop("auto_advance_at", None)


def run_auto_advance(game, now=None):
    """倒计时到点时替主持人推进；条件不成立或推进被拒时撤销倒计时。"""
    now = clock.now() if now is None else now
    deadline = game["public"].get("auto_advance_at")
    if not deadline or deadline > now or game["status"] != "playing":
        return []
    events = []
    if auto_advance_ready(game) or discussion_end_ready(game):
        try:
            advance(game, events)
            sync_auto_advance(game)
        except GameError:
            game["public"].pop("auto_advance_at", None)
    else:
        game["public"].pop("auto_advance_at", None)
    game["version"] += 1
    return events


def timeout_seat(game, events, sid):
    """把一个席位当前未完成的行动按超时（视为放弃）处理；返回是否确有行动被放弃。

    与主持人的30秒警告到点共用同一套分支：夜间视为放弃并确认，顺序发言顺延到
    下一位，提名记作放弃，投票记弃权，处决响应记作确认，穗乃香目击按默认显示，
    「夜间结果与证物」阶段还没决定的复活记作本夜放弃。
    """
    phase = game["phase"]
    witness = next(
        (
            item
            for item in game["pending"]
            if item["kind"] == "honoka_witness" and item["seat_id"] == sid
        ),
        None,
    )
    if witness:
        honoka.resolve_witness(game, events, witness)
    elif phase in {"night", "night_coco"} and sid not in game["night"]["confirmed"]:
        # 已提交寻宝的席位没有「放弃」可言：超时只补确认，寻宝照常结算。
        if not any(
            a["seat_id"] == sid and a["ability"] == "treasure" for a in game["night"]["actions"]
        ):
            clear_seat_actions(game, sid, events)
        game["night"]["confirmed"].append(sid)
        unlock_coco(game, events)
    elif phase == "speech" and game["public"]["speaker"] == sid:
        speech_done(game, events)
    elif phase == "nomination" and sid in pending_nominators(game):
        game.setdefault("nomination_done", []).append(sid)
    elif phase == "voting":
        # 超时＝视为放弃：把还没选的候选全部记成弃票。决斗日「至少同意一张」的
        # 要求在提交时校验，超时不受它拦住（与强制推进的既有语义一致）。
        ballot = game.setdefault("ballots", {}).setdefault(sid, {})
        for item in nomination_rounds(game):
            if seat_choice(game, sid, item["card_id"]) is None:
                ballot[item["card_id"]] = "abstain"
    elif phase == "execution":
        if sid not in game["execution_ready"]:
            game["execution_ready"].append(sid)
    elif phase == "night_results" and sid == pending_revive(game):
        # 「夜间结果与证物」的复活：主持人警告到点或强制推进都按放弃处理，
        # 本人不再有机会撤回当夜的死亡，入口与主持人待办随之消失。
        game["night"]["revive_declined"] = True
    else:
        return False
    game["warnings"].pop(sid, None)
    return True


def timeout_outstanding(game, events):
    """强制推进：本阶段所有未完成的玩家行动立刻按超时处理。

    顺序发言一次只暴露当前发言人，超时后顺延到下一位，所以循环取到没有待办为止；
    每轮都要求至少有一个席位真的被处理，避免任何意外分支让命令空转。
    """
    timed_out = []
    for _ in range(len(game["seats"]) * 2 + 2):
        targets = outstanding_seats(game)
        if not targets or game["status"] != "playing":
            break
        progressed = False
        for sid in targets:
            if timeout_seat(game, events, sid):
                timed_out.append(sid)
                progressed = True
        if not progressed:
            break
    timed_out = list(dict.fromkeys(timed_out))
    if timed_out:
        for sid in timed_out:
            notify(game, events, f"{sid}号未完成的操作已按超时处理。", [sid], "强制推进")
        log_event(
            game,
            "host",
            "主持人强制推进："
            + "、".join(f"{sid}号" for sid in timed_out)
            + "未完成的行动按超时处理",
        )
    return timed_out


def force_advance(game, events):
    """主持人的强制推进：先让所有未完成的玩家行动立刻超时，再推进阶段。

    待裁定事项不算玩家行动，仍由 advance() 拒绝，必须由主持人逐项处理。
    """
    timeout_outstanding(game, events)
    advance(game, events)


def expire_warnings(game, now=None):
    now = clock.now() if now is None else now
    expired = [sid for sid, deadline in game["warnings"].items() if deadline <= now]
    if not expired or game["status"] != "playing":
        return []
    events = []
    for sid in expired:
        timeout_seat(game, events, sid)
        game["warnings"].pop(sid, None)
        # 警告与超时只私下告知被警告的席位，不对全场公告。
        notify(
            game,
            events,
            f"{sid}号警告时间已到，当前未完成操作按放弃处理。",
            [sid],
            "警告超时",
        )
        if game["status"] != "playing":
            # 过期结算可能已结束对局：不再写状态或处理其余席位。
            break
    game["deadline"] = min(game["warnings"].values(), default=None)
    sync_speaker(game, events)
    sync_auto_advance(game)
    game["version"] += 1
    return events
