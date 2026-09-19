"""Game commands and phase flow; callers commit a copied state atomically."""

from copy import deepcopy
from random import SystemRandom
from time import time

from .actions import (
    actions_for,
    can_day_ability,
    challengeable,
    claimable,
    night_abilities,
    outstanding_seats,
)
from .catalog import AUTO_ADVANCE_DELAY, AUTO_PHASES, DAY_ABILITIES, PHASES, ROLES
from .resolution import (
    begin_night,
    damage_preview,
    death_batch,
    eliminate_seat,
    information,
    lock_night,
    prepare_night_preview,
    revive,
    swap_cards,
    target_allowed,
    unlock_coco,
)
from .state import (
    GameError,
    audience,
    chat_event,
    check_winner,
    clear_seat_actions,
    current,
    deal_cards,
    eligible_voters,
    finish,
    hiro_dilemma,
    hiro_pending,
    living,
    lost_by_challenge,
    pending_nominators,
    notify,
    owner,
    pending,
    player_seat,
    poisoned,
    present,
    require,
    rewind,
    role_card,
    save_snapshot,
    seat,
    snapshot_for,
    uid,
)


def validate_command(game, actor, action, payload):
    require(isinstance(action, str) and isinstance(payload, dict), "操作格式无效")
    require(actor.get("kind") in {"host", "player", "spectator"}, "没有操作权限")
    require(actor.get("kind") == "host" or actor.get("game_id") == game["id"], "没有本局操作权限")
    choices = [
        a
        for a in actions_for(game, actor)
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


def set_witch(game, events, cid):
    card = game["cards"][cid]
    require(cid not in {"sherry", "arisa"}, "雪莉与亚里沙不能魔女化")
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
    if cid == "hiro":
        card["states"]["madness_target"] = "emma"


def convert_daily(game, events):
    if game.get("witch_checked_day") == game["day"]:
        # 本日已检测过：主持人纠错改动状态后不再次自动转化，直接开夜。
        begin_night(game, events)
        return
    game["witch_checked_day"] = game["day"]
    for cid in game["codex"]:
        c = game["cards"][cid]
        s = owner(game, cid)
        other = next(game["cards"][x] for x in s["cards"] if x != cid)
        if (
            cid not in {"sherry", "arisa"}
            and c["alive"]
            and not c["witch"]
            and current(game, s) == c
            and other["original_role_id"] not in {"millia", "arisa"}
        ):
            set_witch(game, events, cid)
            begin_night(game, events)
            return
    pending(game, "codex", "魔典已无合法目标：主持人裁定本日转化或耗尽处理")


def millia_swap(game, events, preview, swap):
    """米莉亚临死交换：选好对象就直接换上层牌并重新结算，不设主持人判定点。"""
    left, right = owner(game, "millia"), seat(game, swap["target_seat"])
    swap_cards(game, swap)
    notify(game, events, "米莉亚临死交换已生效。", [left["id"], right["id"]], "角色交换")
    apply_damage(game, events, damage_preview(game, deepcopy(preview["attacks"])))


def apply_damage(game, events, preview, allow_reaction=True):
    millia = role_card(game, "millia")
    # 换牌只从本夜行动里挑：夜间换牌未触发时行动整体保留，白天伤害不得
    # 捡起昨夜残留行动重复结算（希罗回溯规则允许白天触发，不在此限）。
    swap = (
        next(
            (a for a in game["night"]["actions"] if a["ability"] == "swap" and a.get("effective")),
            None,
        )
        if game["half"] == "night"
        else None
    )
    if (
        allow_reaction
        and swap
        and not millia["uses"].get("swap")
        and not poisoned(millia)
        and any(d["target_card"] == "millia" for d in preview["deaths"])
    ):
        millia_swap(game, events, preview, swap)
        return
    hiro = role_card(game, "hiro")
    mode = "witch" if hiro["witch"] else "normal"
    if (
        allow_reaction
        and not poisoned(hiro)
        and not game["spiritual"]["hiro_used"][mode]
        and any(d["target_card"] == "hiro" for d in preview["deaths"])
    ):
        hiro_pending(game, events, mode, preview=preview)
    else:
        death_batch(game, events, preview)


def open_balloon(game, events, organizer, participants):
    balloon = game["public"]["balloon"]
    require(balloon["day"] != game["day"], "本白天已组织过热气球")
    require(
        1 <= len(participants) <= 5 and len(set(participants)) == len(participants),
        "热气球需要1至5名不重复参加者",
    )
    require(all(current(game, p) for p in participants), "参加者必须存活")
    balloon.update(
        {
            "organizer": organizer,
            "participants": list(participants),
            "day": game["day"],
            "status": "collecting",
        }
    )
    game["balloon_choices"] = {}
    annan = owner(game, "annan")["id"]
    if annan in participants:
        # 安安参加即为破坏，不需要她本人或其他操作
        game["balloon_choices"][annan] = "break"
        notify(
            game,
            events,
            f"{annan}号（安安）参加热气球，直接判定为破坏。",
            [annan],
            "热气球",
        )
    notify(
        game,
        events,
        f"热气球开始制作，参加席位：{'、'.join(participants)}；请各自秘密提交选择。",
        alert=True,
    )


def settle_balloon(game, events):
    balloon = game["public"]["balloon"]
    # 未提交者一律按不制作兜底：主持人手动推进不再被收集中的未提交者卡住。
    game["balloon_choices"].update(
        {sid: "skip" for sid in balloon["participants"] if sid not in game["balloon_choices"]}
    )
    choices = {sid: game["balloon_choices"].get(sid, "skip") for sid in balloon["participants"]}
    makers = sum(value == "make" for value in choices.values())
    breakers = [sid for sid, value in choices.items() if value == "break"]
    skipped = [sid for sid, value in choices.items() if value == "skip"]
    delta = 0 if breakers else makers
    balloon["progress"] = 0 if breakers else balloon["progress"] + makers
    balloon["last"] = {
        "day": game["day"],
        "makers": makers,
        "breakers": breakers,
        "skipped": skipped,
        "delta": delta,
    }
    balloon["status"] = "complete"
    for declaration in game["declarations"]:
        if declaration["ability"] == "balloon" and declaration["status"] == "open":
            declaration["status"] = "complete"
    sync_declarations(game)
    notify(
        game,
        events,
        f"热气球制作结束：当前进度{balloon['progress']}/13。",
        alert=True,
    )
    if (
        balloon["progress"] >= 13
        and present(game, "arisa")
        and any(c["alive"] and c["witch"] for c in game["cards"].values())
    ):
        finish(game, events, "good", "热气球达到13并起飞；安安强制落败。", balloon=True)


def resolve_balloon_proposal(game, events):
    """亚里沙不在场：超过半数存活玩家同意就按名单组织，票数不可能过半就作废。"""
    proposal = game.get("balloon_proposal")
    if not proposal:
        return
    alive = living(game)
    agreed = sum(1 for value in proposal["votes"].values() if value)
    if agreed * 2 > len(alive):
        game["balloon_proposal"] = None
        open_balloon(game, events, f"{proposal['by']}号提议", proposal["participants"])
        return
    remaining = len(alive) - len(proposal["votes"])
    if agreed + remaining <= len(alive) / 2:
        game["balloon_proposal"] = None
        notify(game, events, "同意人数已无法过半，本次热气球提议作废，可以重新提议。", alert=True)
        return
    notify(
        game,
        events,
        f"热气球名单表决中：同意{agreed}人／存活{len(alive)}人，需要超过{len(alive) // 2}人同意。",
    )


def speech_done(game, events):
    public = game["public"]
    if public.get("interrupted_speaker"):
        resumed = public.pop("interrupted_speaker")
        queued = game.get("speech_queued", {})
        if resumed in queued:
            # 被打断者若已提前写好发言，恢复发言权时先公开，内容不随打断丢失。
            chat_event(game, events, resumed, f"{queued.pop(resumed)}")
        public["speaker"] = resumed
        return
    public["speaker"] = next_speaker(game, public["speaker"], events)


def next_speaker(game, current_speaker, events):
    """下一位发言人；提前发言的席位在此刻才公开内容，宣布不发言的直接跳过。"""
    order = game["public"]["speech_order"]
    passed = set(game.get("speech_passed", []))
    queued = game.get("speech_queued", {})
    index = order.index(current_speaker) + 1 if current_speaker in order else 0
    while index < len(order) and order[index] in passed:
        sid = order[index]
        if sid in queued:
            chat_event(game, events, sid, f"{queued.pop(sid)}")
        index += 1
    return order[index] if index < len(order) else None


def speech_plan(game, dead_first):
    """死者先发言；其余在顺序与逆序间取让魔女化玩家更早发言的一侧。"""
    seats = [s["id"] for s in game["seats"]]
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


def brainwash_targets(game):
    active = game["brainwash"]
    if "annan" in active and "marg" in active:
        return set()
    return set(active.values())


def nomination_rounds(game):
    """同一张牌被多人提名只投一轮，先提名者排在前面。"""
    rounds, seen = [], set()
    for item in game["nominations"]:
        if item["card_id"] in seen:
            continue
        seen.add(item["card_id"])
        rounds.append(item)
    return rounds


def nomination_votes(game, nominee):
    """提名过本候选的玩家直接投同意票，省掉一次重复点击。"""
    voters = {s["id"] for s in eligible_voters(game)}
    forced = brainwash_targets(game)
    bound = game["spiritual"]["sherry_bound"] and nominee["card_id"] == "hanna"
    return {
        item["by"]: "abstain" if item["by"] in forced else "yes"
        for item in game["nominations"]
        if item["card_id"] == nominee["card_id"]
        and item["by"] in voters
        and not (bound and current(game, item["by"])["id"] == "sherry")
    }


def open_vote(game, events):
    rounds = nomination_rounds(game)
    index = len(game["vote_rounds"])
    if index >= len(rounds):
        for cid, day in game["spiritual"]["annan_penalty"].items():
            if day == game["day"] and game["cards"][cid]["alive"] and cid not in game["execution"]:
                game["execution"].append(cid)
        game["phase"] = "execution"
        game["execution_ready"] = []
        game["execution_shots"] = []
        game["public"]["votes"]["execution_seats"] = list(
            dict.fromkeys(owner(game, cid)["id"] for cid in game["execution"])
        )
        return
    game["phase"] = "voting"
    nominee = rounds[index]
    game["votes"] = nomination_votes(game, nominee)
    for sid in game["votes"]:
        notify(
            game,
            events,
            f"{nominee['seat_id']}号就是你先前提名的候选，已按提名自动投票。",
            [sid],
            "自动投票",
        )
    game["public"]["votes"] = {
        "candidate": nominee["seat_id"],
        "round": index + 1,
        "total": len(rounds),
        "results": deepcopy(game["vote_rounds"]),
    }
    notify(
        game,
        events,
        f"开始对{nominee['seat_id']}号候选投票；严格超过有投票权存活玩家的一半方可处决。",
        alert=True,
    )


def close_vote(game, events):
    voters = eligible_voters(game)
    require(all(s["id"] in game["votes"] for s in voters), "仍有玩家未投票，可先警告")
    forced = brainwash_targets(game)
    nominee = nomination_rounds(game)[len(game["vote_rounds"])]
    yes = sum(
        game["votes"].get(s["id"]) == "yes"
        and s["id"] not in forced
        and not (
            game["spiritual"]["sherry_bound"]
            and current(game, s)["id"] == "sherry"
            and nominee["card_id"] == "hanna"
        )
        for s in voters
    )
    n = len(voters)
    passed = yes * 2 > n
    record = {
        "candidate": nominee["seat_id"],
        "yes": yes,
        "denominator": n,
        "threshold": n // 2 + 1,
        "passed": passed,
    }
    game["vote_rounds"].append(record)
    if passed and nominee["card_id"] not in game["execution"]:
        game["execution"].append(nominee["card_id"])
    notify(
        game,
        events,
        f"{nominee['seat_id']}号：同意{yes}/{n}，门槛{n // 2 + 1}，{'通过处决' if passed else '未通过'}。",
        alert=True,
    )
    open_vote(game, events)


def advance(game, events):
    require(not game["pending"], "仍有待裁定事项，请逐项处理后推进")
    phase = game["phase"]
    if phase == "witch":
        convert_daily(game, events)
    elif phase in {"night", "night_coco"}:
        unlock_coco(game, events)
        lock_night(game, events)
    elif phase == "night_review":
        require(game["night"]["preview"] is not None, "尚无预结算结果")
        death_batch(game, events, game["night"]["preview"])
        game["phase"] = "night_results"
    elif phase == "night_results":
        require(
            not game["winner_candidate"],
            "本夜已有胜负候选，请先完成连锁并宣判，不能切换为白天后重新判定",
        )
        game["half"] = "day"
        game["phase"] = "speech"
        game["day_binding"] = (
            {"day": game["day"], "intact": True}
            if present(game, "sherry") and present(game, "hanna")
            else None
        )
        dead_first = [
            d["seat_id"] for d in game["deaths"] if d["day"] == game["day"] and d["half"] == "night"
        ]
        order = game["public"]["speech_order"] or speech_plan(game, dead_first)
        game["public"]["speech_order"] = order
        game["public"]["speaker"] = next_speaker(game, None, events)
        for notice in game["queued_notices"]:
            notify(game, events, notice, alert=True)
        game["queued_notices"] = []
        game["queued_reveals"] = []
        game["brainwash"] = {}
        game["nominations"] = []
        game["nomination_done"] = []
        game["vote_rounds"] = []
        game["execution"] = []
        game["balloon_proposal"] = None
        for declaration in game["declarations"]:
            if declaration["status"] == "open":
                declaration["status"] = "complete"
        game["pending"] = [p for p in game["pending"] if not p.get("declaration_id")]
        sync_declarations(game)
    elif phase == "speech":
        require(game["public"]["speaker"] is None, "仍有顺序发言未完成，请玩家确认或警告超时")
        game["phase"] = "discussion"
    elif phase == "discussion":
        game["phase"] = "balloon"
    elif phase == "balloon":
        # 先结算名单表决（通过即组织，不可能过半即作废），再清空，不静默丢弃。
        if game["balloon_proposal"]:
            resolve_balloon_proposal(game, events)
            game["balloon_proposal"] = None
        if game["public"]["balloon"]["status"] == "collecting":
            settle_balloon(game, events)
        if game["status"] != "ended":
            game["phase"] = "nomination"
    elif phase == "nomination":
        require(not pending_nominators(game), "仍有玩家未提名或放弃，可警告后等待30秒")
        open_vote(game, events)
    elif phase == "voting":
        close_vote(game, events)
    elif phase == "execution":
        awaiting = {
            owner(game, cid)["id"]
            for cid in game["execution"]
            if game["cards"][cid]["alive"]
            and cid == "nanoka"
            and role_card(game, cid)["uses"].get("bullets", 0) > 0
        }
        require(awaiting.issubset(game["execution_ready"]), "临刑开枪响应尚未确认，可先警告")
        attacks = [
            {"target_card": cid, "cause": "execution", "source_card": None}
            for cid in game["execution"]
        ]
        attacks.extend(game.get("execution_shots", []))
        preview = damage_preview(game, attacks)
        apply_damage(game, events, preview)
        executed = [d["target_card"] for d in preview["deaths"] if d["cause"] == "execution"]
        if executed and present(game, "nanoka"):
            information(
                game,
                events,
                role_card(game, "nanoka"),
                "白天幻视",
                "当天被投出者中"
                + (
                    "有魔女。"
                    if any(game["cards"][cid]["witch"] for cid in executed)
                    else "没有魔女。"
                ),
            )
        game["phase"] = "dusk"
    elif phase == "dusk":
        require(not game["winner_candidate"], "已有胜负候选，请确认本半天所有效果后宣判或裁定纠错")
        binding = game["day_binding"]
        if binding and binding["intact"] and present(game, "sherry") and present(game, "hanna"):
            game["spiritual"]["sherry_bound"] = True
            notify(
                game,
                events,
                "你与汉娜已共同度过完整白天，绑定生效。",
                [owner(game, "sherry")["id"]],
                "雪莉绑定",
            )
        game["day"] += 1
        game["half"] = "night"
        game["phase"] = "witch"
        game["public"]["speaker"] = None
        game["public"]["speech_order"] = []
        game["speech_passed"] = []
        game["speech_queued"] = {}
    else:
        raise GameError("当前阶段不能推进")
    game["warnings"] = {}
    game["deadline"] = None
    save_snapshot(game)
    if game["status"] != "ended":
        notify(game, events, f"第{game['day']}天 · {PHASES[game['phase']]}。")


def execute_declaration(game, events, declaration):
    if declaration["executed"]:
        return
    data = declaration["data"]
    cid, sid, ability = declaration["card_id"], declaration["seat_id"], declaration["ability"]
    card = game["cards"][cid]
    if not declaration["fake"] and poisoned(card):
        declaration["executed"] = True
        notify(game, events, "本次效果技能因中毒不生效。", [sid])
        return
    target = data.get("target")
    target_card = current(game, target) if target else None
    if target:
        require(target_card is not None, "声明目标已不在场，请停止声明并重新裁定")
    if ability in {"interrupt", "last_speaker"}:
        card["uses"]["interrupt_day"] = game["day"]
        if ability == "last_speaker":
            order = game["public"]["speech_order"]
            game["public"]["speech_order"] = [x for x in order if x != sid] + [sid]
            if game["public"]["speaker"] == sid:
                game["public"]["speaker"] = next(
                    (x for x in game["public"]["speech_order"] if x != sid), sid
                )
        else:
            require(target != sid, "不能打断自己的发言")
            if game["phase"] == "speech":
                require(game["public"]["speaker"] == target, "只能打断当前发言者")
            game["public"]["interrupted_speaker"] = target
            game["public"]["speaker"] = sid
    elif ability == "love":
        card["uses"]["love_day"] = game["day"]
        card["states"]["madness_target"] = target_card["id"]
    elif ability == "gaze":
        card["uses"]["gaze_day"] = game["day"]
        game["gaze"] = {"cards": [cid, target_card["id"]], "night_day": game["day"] + 1}
    elif ability == "brainwash":
        game["brainwash"][cid] = target
        if cid == "annan" and not card["witch"]:
            marg = role_card(game, "marg")
            if present(game, "marg") and marg["witch"]:
                marg["states"]["learned_brainwash"] = True
                notify(
                    game,
                    events,
                    "普通安安已发动洗脑，你已学会洗脑；同时发动时互相抵消。",
                    [owner(game, "marg")["id"]],
                )
    elif ability == "mass_brainwash":
        card["uses"]["mass_brainwash"] = True
        if target_card["id"] not in game["execution"]:
            game["execution"].append(target_card["id"])
        game["spiritual"]["annan_penalty"][cid] = game["day"] + 1
        notify(game, events, f"{target}号进入本轮处决名单。", alert=True)
    elif ability == "photo":
        require(data.get("text") or data.get("image_id"), "照片需要真实内容或画面")
        photo = {
            "id": uid(),
            "sender": sid,
            "recipient": target,
            "allowed": False,
            "text": data.get("text", ""),
            "image_id": data.get("image_id"),
        }
        game["photos"].append(photo)
        notify(
            game,
            events,
            photo["text"] or "收到照片，可自愿授权发送者查看你的夜间行动。",
            [target],
            "收到照片",
            photo["image_id"],
        )
    elif ability == "balloon":
        participants = [sid] + [p for p in data["participants"] if p != sid]
        open_balloon(game, events, sid, participants)
    declaration["executed"] = True


def resolve_pending(game, events, data):
    item = next(p for p in game["pending"] if p["id"] == data["pending_id"])
    kind = item["kind"]
    if kind == "information":
        notify(
            game, events, data["text"], [item["seat_id"]], "主持人裁定信息", item.get("image_id")
        )
    elif kind == "hiro":
        if data["snapshot"] == "decline":
            if item.get("preview"):
                apply_damage(game, events, item["preview"], allow_reaction=False)
        else:
            snap = next(s for s in game["snapshots"] if s["id"] == data["snapshot"])
            if snap["day"] != item["expected_day"] or snap["phase"] != item["expected_phase"]:
                require(bool(data.get("reason", "").strip()), "非前一天对应时点需填写裁定理由")
            rewind(game, data["snapshot"], events, item["mode"], data.get("keep_states", []))
            return
    elif kind == "suspects":
        suspects = data["suspects"]
        source = item.get("source_card") or data.get("true_source")
        if source:
            source = game["cards"][source]["states"].get("framed_killer", source)
        omit_leia = data.get("omit_leia", False)
        require(not omit_leia or role_card(game, "leia")["witch"], "只有魔女蕾雅可裁定不入名单")
        require("hanna" in suspects, "名单必须包含汉娜")
        require(
            not source or source in suspects or source == "leia" and omit_leia,
            "名单必须包含技能处理后的真凶",
        )
        require(not (omit_leia and "leia" in suspects), "选择不列入蕾雅时请移除蕾雅")
        shown = [
            game["cards"][cid]["states"].get("witness_role", cid)
            if cid == "honoka" and game["cards"][cid]["witch"]
            else cid
            for cid in suspects
        ]
        notify(
            game,
            events,
            "三名疑似凶手：" + "、".join(ROLES[cid]["name"] for cid in shown),
            [item["seat_id"]],
            "夜间目击名单",
        )
        victim_seat = seat(game, item["seat_id"])
        if not current(game, victim_seat):
            game["cards"][item["victim"]]["states"]["evidence_allowed"] = True
    elif kind == "lower_entry":
        if (
            data.get("allow")
            and game["half"] == "night"
            and game["phase"] in {"night", "night_coco"}
            and not game["night"]["locked"]
        ):
            game["night"]["actors"][item["seat_id"]] = item["card_id"]
            clear_seat_actions(game, item["seat_id"])
        game["cards"][item["card_id"]]["states"]["entry_blocked_at"] = (
            None if data.get("allow") else f"{game['day']}:{game['phase']}"
        )
    elif kind == "declaration":
        declaration = next(d for d in game["declarations"] if d["id"] == item["declaration_id"])
        require(declaration["status"] == "open", "该声明已停止")
        outcome = data["outcome"]
        if outcome != "stop":
            execute_declaration(game, events, declaration)
        if outcome == "execute":
            item["title"] = item["text"] = (
                f"{declaration['seat_id']}号声明效果已执行：结束质疑窗口或停止后续"
            )
            return
        declaration["status"] = "complete" if outcome == "complete" else "stopped"
        sync_declarations(game)
    elif kind == "water":
        outcome = data["outcome"]
        if outcome == "cancel":
            game["water"]["used"] = False
        else:
            attack = {
                "target_card": item["target_card"],
                "source_card": item["source_card"],
                "cause": "water",
                "hide_cause": item["hide_cause"],
                "unconditional": outcome == "unconditional",
                "injury": outcome == "injure",
            }
            if game["half"] == "night" and game["phase"] in {"night", "night_coco", "night_review"}:
                game["night"].setdefault("extra_attacks", []).append(attack)
                if game["night"]["locked"]:
                    prepare_night_preview(game)
            else:
                apply_damage(game, events, damage_preview(game, [attack]))
        notify(game, events, data["reason"], [item["seat_id"]], "13水裁定")
    elif kind == "evidence":
        if data.get("allow"):
            recipients = None if data.get("public") else data.get("recipients", [])
            require(recipients is None or recipients, "请选择公开或指定接收者")
            if item.get("text") or item.get("image_id"):
                notify(
                    game,
                    events,
                    item.get("text") or "死者留下证物。",
                    recipients,
                    "遗留证物",
                    item.get("image_id"),
                )
            for painting in item.get("paintings", []):
                notify(
                    game,
                    events,
                    painting.get("text") or "诺亚遗留画作",
                    recipients,
                    "画作证物",
                    painting["image_id"],
                )
    elif kind == "codex":
        if data["outcome"] == "convert":
            require(data.get("target") in game["cards"], "请选择特殊转化目标")
            set_witch(game, events, data["target"])
        notify(game, events, "主持人已处理本日魔女化检测。")
        begin_night(game, events)
    elif kind == "madness":
        if data["outcome"] == "penalty":
            game["public"]["achievements_enabled"] = False
            cid = data["target"]
            effect = data["penalty"]
            require(effect != "none" or bool(data["reason"].strip()), "请明确不利裁定")
            if effect == "death":
                apply_damage(
                    game,
                    events,
                    damage_preview(
                        game, [{"target_card": cid, "cause": "madness", "unconditional": True}]
                    ),
                )
            elif effect == "poison":
                game["cards"][cid]["states"]["poisoned"] = True
            elif effect == "lose":
                game["spiritual"]["personal_losses"].extend(
                    audience(game, [owner(game, cid)["id"]])
                )
        notify(game, events, data["reason"], [item["seat_id"]], "疯狂行为裁定")
    elif kind == "reaction":
        require(data["proceed"], "请确认继续结算")
        apply_damage(game, events, item["preview"], allow_reaction=False)
    game["pending"] = [p for p in game["pending"] if p["id"] != item["id"]]


def sync_declarations(game):
    game["public"]["declarations"] = [
        {
            "id": d["id"],
            "seat_id": d["seat_id"],
            "ability": d["ability"],
            "label": DAY_ABILITIES[d["ability"]][1],
            "status": d["status"],
        }
        for d in game["declarations"]
        if d["day"] == game["day"]
    ]


def host_command(game, events, action, data):
    if action == "host.start":
        require(game["status"] == "lobby" and game["phase"] == "ordering", "请先全员准备并发牌")
        require(
            all(s["occupant_id"] and s["ready"] for s in game["seats"]),
            "需要7名玩家全部入座、确认上下牌并准备",
        )
        for s in game["seats"]:
            s["avatar_role_id"] = current(game, s)["role_id"]
        honoka = role_card(game, "honoka")
        honoka_seat = owner(game, "honoka")
        if current(game, honoka_seat)["id"] == "honoka" and honoka["states"].get("disguise"):
            honoka_seat["avatar_role_id"] = honoka["states"]["disguise"]
            honoka["states"]["disguise_locked"] = True
        else:
            honoka["states"].pop("disguise", None)
        game["status"] = "playing"
        game["phase"] = "witch"
        sid = honoka_seat["id"]
        information(
            game,
            events,
            honoka,
            "开局上层角色",
            "；".join(
                f"{s['id']}号：{ROLES[current(game, s)['role_id']]['name']}"
                for s in game["seats"]
                if s["id"] != sid
            ),
        )
        save_snapshot(game)
        notify(game, events, "所有上下牌已锁定，对局开始。")
    elif action == "host.advance":
        advance(game, events)
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
        ids = [s["id"] for s in game["seats"]]
        index = ids.index(data["start"])
        order = ids[index:] + ids[:index]
        if data["direction"] == "desc":
            order = [order[0]] + order[1:][::-1]
        game["public"]["speech_order"] = order
        if game["phase"] == "speech":
            game["public"]["speaker"] = order[0]
        notify(game, events, "发言顺序：" + " → ".join(order))
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
            game["warnings"][sid] = time() + 30
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
        require(not game["water"]["used"], "本局唯一13水已使用")
        require(not any(p["kind"] == "water" for p in game["pending"]), "13水正在裁定使用")
        old = game["water"]["holder"]
        game["water"]["holder"] = data["seat_id"]
        if old and old != data["seat_id"]:
            notify(game, events, "13水已由主持人收回。", [old], "13水")
        notify(
            game,
            events,
            "你获得本局唯一一瓶13水，使用时机与互动由主持人裁定。",
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
                prepare_night_preview(game)
        else:
            apply_damage(game, events, damage_preview(game, attacks))
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
                    damage_preview(
                        game,
                        [
                            {
                                "target_card": cid,
                                "cause": "host",
                                "unconditional": True,
                                "allow_lower": True,
                            }
                        ],
                    ),
                )
        elif state == "injured":
            card["injured"] = value
        else:
            if state == "puppet":
                require(not value or data.get("master"), "傀儡需指定主人")
                value = data.get("master") if value else None
            card["states"][state] = value
            if data.get("persistent"):
                game["spiritual"]["persistent_states"].setdefault(cid, {})[state] = value
        check_winner(game)
        notify(
            game,
            events,
            data["reason"],
            None if data.get("public") else [owner(game, cid)["id"]],
            "主持人状态裁定",
        )
        if game["phase"] == "night_review":
            prepare_night_preview(game)
    elif action == "host.information":
        recipients = None if data.get("public") else data.get("recipients", [])
        require(recipients is None or recipients, "请选择公开或指定接收者")
        require(data.get("text") or data.get("image_id"), "信息需要正文或图像")
        notify(game, events, data.get("text", ""), recipients, data["title"], data.get("image_id"))
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
            witches = [c for c in game["cards"].values() if c["alive"] and c["witch"]]
            require(
                len(witches) == 1
                and witches[0]["id"] == "coco"
                and owner(game, "coco")["id"] in game["surrenders"],
                "仅剩可可一名魔女且本人申请时，魔女才能交牌",
            )
        else:
            good_seats = [
                s["id"]
                for s in game["seats"]
                if any(not game["cards"][cid]["witch"] for cid in s["cards"])
            ]
            require(
                all(sid in game["surrenders"] for sid in good_seats), "需要所有好人分别私信同意交牌"
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
    "balloon": {"balloon.choose"},
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
    elif action == "player.profile":
        require(1 <= len(data["name"].strip()) <= 30, "公开称呼需为1至30字")
        s["name"] = data["name"].strip()
    elif action == "night.submit":
        ability = data["ability"]
        cid = game["night"]["actors"][sid]
        card = game["cards"][cid]
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
        if target:
            entry["target_seat"], entry["target_card"] = data["target"], target["id"]
        game["night"]["actions"] = [
            a
            for a in game["night"]["actions"]
            if not (a["seat_id"] == sid and a["ability"] == ability)
        ] + [entry]
    elif action == "night.clear":
        clear_seat_actions(game, sid)
    elif action == "night.confirm":
        actions = [a for a in game["night"]["actions"] if a["seat_id"] == sid]
        card = game["cards"][game["night"]["actors"][sid]]
        if card["id"] == "hiro" and card["witch"]:
            emma = role_card(game, "emma")
            can_attack_emma = (
                emma["alive"]
                and current(game, owner(game, "emma")) == emma
                and target_allowed(game, "emma")
            )
            attacked = any(
                a["ability"] == "knife" and a.get("target_card") == "emma" for a in actions
            )
            if can_attack_emma and not attacked:
                require(
                    not game["spiritual"]["hiro_exception"],
                    "希罗唯一一夜的疯狂攻击例外已用，且艾玛在合法攻击范围内",
                )
                game["spiritual"]["hiro_exception"] = True
        elif card["states"].get("madness_target"):
            target = game["cards"].get(card["states"]["madness_target"])
            attacks = set(night_abilities(game, card)) & {
                "knife",
                "shoot",
                "spear",
                "extra_kill",
                "massacre",
            }
            if poisoned(card):
                attacks &= {"knife"}
            if (
                attacks
                and target
                and target["alive"]
                and current(game, owner(game, target["id"])) == target
                and target_allowed(game, target["id"])
            ):
                attacked = any(
                    a["ability"] in attacks
                    and (
                        a.get("target_card") == target["id"]
                        or a["ability"] == "massacre"
                        and target["id"] != card["id"]
                    )
                    for a in actions
                )
                require(attacked, "拥有攻击能力时，必须攻击合法范围内的疯狂目标；注视范围限制优先")
        for a in actions:
            a["confirmed"] = True
            if a["ability"] == "paint":
                card["states"].setdefault("paintings", []).append(
                    {"image_id": a["image_id"], "text": a.get("text", ""), "day": game["day"]}
                )
                notify(
                    game,
                    events,
                    a.get("text") or "本夜画作已保存。",
                    [sid],
                    "我的画作",
                    a["image_id"],
                )
        if card["id"] == "noah":
            card["states"]["paint_done"] = game["day"]
        game["night"]["confirmed"].append(sid)
        unlock_coco(game, events)
    elif action == "day.skill":
        ability = data["ability"]
        # 穗乃香只能假装自己示人身份的技能
        fake = card["id"] == "honoka" and ability in claimable(card["states"].get("disguise"))
        require(fake or can_day_ability(game, card, ability), "此时不能声明该技能")
        d = {
            "id": uid(),
            "day": game["day"],
            "seat_id": sid,
            "card_id": card["id"],
            "ability": ability,
            "fake": fake,
            "by_host": by_host,
            "data": deepcopy(data),
            "status": "open",
            "executed": False,
        }
        game["declarations"].append(d)
        if fake:
            # 规则九：伪装能不能成立、按什么结算由主持人裁定，仍保留主持人判定点。
            pending(
                game,
                "declaration",
                f"{sid}号声称{DAY_ABILITIES[ability][1]}（伪装）：裁定是否按真实流程结算",
                declaration_id=d["id"],
            )
        else:
            # 真实技能（含热气球）按技能条目直接结算，声明保持开放以保留质疑窗口。
            execute_declaration(game, events, d)
        sync_declarations(game)
        notify(
            game,
            events,
            f"{sid}号声明发动「{DAY_ABILITIES[ability][1]}」，其他玩家可质疑。",
            alert=True,
        )
    elif action == "day.challenge":
        d = next(d for d in game["declarations"] if d["id"] == data["declaration_id"])
        require(d["status"] == "open", "该技能声明已结束")
        require(d["seat_id"] != sid, "不可质疑自己")
        require(challengeable(game, d), "该技能不能质疑")
        require(not lost_by_challenge(game, s), "质疑失败后不能再质疑")
        if d["fake"]:
            d["status"] = "stopped"
            game["pending"] = [p for p in game["pending"] if p.get("declaration_id") != d["id"]]
            notify(
                game,
                events,
                f"{sid}号质疑成功：伪装技能尚未完成的部分停止，已执行部分不撤销。",
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
    elif action == "honoka.disguise":
        hc = game["cards"]["honoka"]
        require(owner(game, "honoka")["id"] == sid, "只有穗乃香可以选择示人角色")
        if game["status"] == "lobby":
            hc["states"]["disguise"] = data["role"]
            notify(
                game,
                events,
                f"开局前示人选择已记录：{ROLES[data['role']]['name']}（仅当穗乃香在上层时生效）。",
                [sid],
                "穗乃香示人",
            )
        else:
            require(card is not None and card["id"] == "honoka", "只有穗乃香登场时可以选择示人角色")
            require(not hc["states"].get("disguise_locked"), "示人角色已经确定，不能再更改")
            hc["states"]["disguise_locked"] = True
            s["avatar_role_id"] = data["role"]
            notify(game, events, f"{sid}号示人为{ROLES[data['role']]['name']}。", [], "穗乃香示人")
    elif action == "honoka.witness":
        card["states"]["witness_role"] = data["role"]
    elif action == "hiro.exit":
        attack = {"target_card": card["id"], "cause": "voluntary", "unconditional": True}
        if game["half"] == "night" and game["phase"] in {"night", "night_coco", "night_review"}:
            game["night"].setdefault("extra_attacks", []).append(attack)
            if game["night"]["locked"]:
                prepare_night_preview(game)
        else:
            apply_damage(game, events, damage_preview(game, [attack]))
    elif action == "speech.done":
        if sid == game["public"]["speaker"]:
            speech_done(game, events)
        else:
            require(sid in game["public"]["speech_order"], "你不在本次发言顺序里")
            require(sid not in game.get("speech_passed", []), "你已经处理过本次发言")
            game.setdefault("speech_passed", []).append(sid)
            notify(
                game,
                events,
                f"{sid}号本轮不发言，轮到其顺序时自动跳过。",
            )
    elif action == "speech.speak":
        require(sid in game["public"]["speech_order"], "你不在本次发言顺序里")
        require(sid not in game.get("speech_passed", []), "你已经处理过本次发言")
        text = data["text"].strip()
        require(text, "请先写下发言内容")
        if sid == game["public"]["speaker"]:
            chat_event(game, events, sid, text)
            game.setdefault("speech_passed", []).append(sid)
            speech_done(game, events)
        else:
            game.setdefault("speech_queued", {})[sid] = text
            game.setdefault("speech_passed", []).append(sid)
            notify(game, events, f"{sid}号已写好发言，轮到时自动公开。")
    elif action == "marg.mimic":
        text = data["text"].strip()
        require(text, "请先写下发言内容")
        chat_event(game, events, data["target"], text, mimic_seat_id=sid)
    elif action == "vote.nominate":
        target = current(game, data["target"])
        game["nominations"].append({"seat_id": data["target"], "card_id": target["id"], "by": sid})
        game["public"]["nominations"] = [
            {"seat_id": n["seat_id"], "by": n["by"]} for n in game["nominations"]
        ]
        notify(game, events, f"{sid}号提名{data['target']}号。")
        game.setdefault("nomination_done", []).append(sid)
    elif action == "vote.pass":
        game.setdefault("nomination_done", []).append(sid)
        notify(game, events, f"{sid}号放弃本次提名。")
    elif action == "vote.cast":
        target = nomination_rounds(game)[len(game["vote_rounds"])]["card_id"]
        require(
            not (
                data["choice"] == "yes"
                and card["id"] == "sherry"
                and game["spiritual"]["sherry_bound"]
                and target == "hanna"
            ),
            "雪莉不能同意处决绑定的汉娜",
        )
        cast = "abstain" if sid in brainwash_targets(game) else data["choice"]
        game["votes"][sid] = cast
        if cast != data["choice"]:
            labels = {"yes": "同意", "no": "不同意", "abstain": "弃票"}
            notify(
                game,
                events,
                f"受洗脑影响，你选择的「{labels[data['choice']]}」已按弃票记录。",
                [sid],
                "洗脑投票",
            )
    elif action == "execution.shoot":
        card["uses"]["bullets"] -= 1
        denominator = 3 if card["witch"] else 6
        roll = SystemRandom().randrange(denominator) + 1
        target = current(game, data["target"])
        game.setdefault("execution_rolls", []).append(
            {
                "day": game["day"],
                "roll": roll,
                "denominator": denominator,
                "target_card": target["id"],
            }
        )
        if roll == 1 and not poisoned(card):
            game["execution_shots"].append(
                {"target_card": target["id"], "source_card": card["id"], "cause": "shoot"}
            )
        game["execution_ready"].append(sid)
        notify(
            game,
            events,
            f"{sid}号临刑开枪，命中率1/{denominator}，{'命中' if roll == 1 and not poisoned(card) else '未造成有效命中'}。",
            alert=True,
        )
    elif action == "execution.confirm":
        game["execution_ready"].append(sid)
    elif action == "balloon.choose":
        balloon = game["public"]["balloon"]
        require(
            balloon["status"] == "collecting" and sid in balloon["participants"],
            "你不在本次热气球名单里",
        )
        require(data["choice"] in {"make", "skip", "break"}, "不合法的热气球选择")
        require(
            data["choice"] != "break" or card["witch"] or card["role_id"] == "annan",
            "除安安以外的好人不能选择破坏热气球",
        )
        game["balloon_choices"][sid] = data["choice"]
        notify(game, events, "热气球选择已提交。", [sid])
        if set(balloon["participants"]).issubset(game["balloon_choices"]):
            settle_balloon(game, events)
    elif action == "balloon.propose":
        require(game["half"] == "day" and not present(game, "arisa"), "当前不能由玩家提议热气球")
        require(game["public"]["balloon"]["day"] != game["day"], "本白天已组织过热气球")
        require(not game["balloon_proposal"], "已有一份待表决的名单")
        participants = list(dict.fromkeys(data["participants"]))
        require(1 <= len(participants) <= 5, "名单需要1至5名不重复玩家")
        require(all(current(game, p) for p in participants), "名单内玩家必须存活")
        game["balloon_proposal"] = {"by": sid, "participants": participants, "votes": {sid: True}}
        notify(
            game,
            events,
            f"{sid}号提议热气球参加者：{'、'.join(participants)}；请其他玩家表决。",
            alert=True,
        )
        resolve_balloon_proposal(game, events)
    elif action in {"balloon.agree", "balloon.decline"}:
        proposal = game["balloon_proposal"]
        require(proposal, "当前没有待表决的热气球名单")
        require(sid not in proposal["votes"], "你已经表决过这份名单")
        proposal["votes"][sid] = action == "balloon.agree"
        resolve_balloon_proposal(game, events)
    elif action == "hiro.decline":
        item = hiro_dilemma(game, sid)
        require(item is not None, "当前没有等待你决定的重溯")
        game["pending"] = [p for p in game["pending"] if p["id"] != item["id"]]
        if item.get("preview"):
            apply_damage(game, events, item["preview"], allow_reaction=False)
        else:
            notify(game, events, "按预结算继续。", [sid], "希罗回溯")
    elif action == "hiro.rewind":
        item = hiro_dilemma(game, sid)
        require(item is not None, "当前没有等待你决定的重溯")
        snap = snapshot_for(game, item)
        require(snap is not None, "前一天同一时点没有可用快照，请由主持人裁定")
        rewind(game, snap["id"], events, item["mode"])
        return
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
        require(card is not None, "当前没有可使用13水的角色，需主持人裁定")
        game["water"]["used"] = True
        pending(
            game,
            "water",
            f"{sid}号使用13水：裁定时机与庇护互动",
            seat_id=sid,
            target_card=target["id"],
            source_card=card["id"],
            hide_cause=bool(data.get("hide_cause") and card["id"] == "meruru" and card["witch"]),
        )
    elif action == "meruru.revive":
        card["uses"]["revive"] = True
        if not poisoned(card):
            death = next(d for d in game["deaths"] if d["id"] == data["death_id"])
            revive(game, events, death["target_card"], puppet=card["id"])
        else:
            notify(game, events, "复活效果因中毒未生效。", [sid])
    elif action == "evidence.submit":
        dead = game["cards"][data["card_id"]]
        paintings = [
            p
            for p in dead["states"].get("paintings", [])
            if p["image_id"] in data.get("paintings", [])
        ]
        require(data.get("text") or data.get("image_id") or paintings, "至少选择一个证物或已画作品")
        dead["states"]["evidence_used"] = True
        pending(
            game,
            "evidence",
            f"{sid}号遗留证物：裁定内容与公开范围",
            seat_id=sid,
            text=data.get("text", ""),
            image_id=data.get("image_id"),
            paintings=paintings,
        )
    elif action == "player.surrender":
        if sid not in game["surrenders"]:
            game["surrenders"].append(sid)
        notify(game, events, "交牌意向已私信主持人；未满足集体条件前继续游戏。", [sid], "交牌申请")
    if sid in game["warnings"] and action in PHASE_ACTIONS.get(phase, ()):
        del game["warnings"][sid]
        game["deadline"] = min(game["warnings"].values(), default=None)


def apply_command(game, actor, action, payload, *, by_host=False):
    require(game["status"] != "ended", "对局已结束，不能再操作")
    validate_command(game, actor, action, payload)
    events = []
    if actor["kind"] == "host":
        host_command(game, events, action, payload)
    else:
        player_command(game, actor, events, action, payload, by_host=by_host)
    if by_host and actor["kind"] == "player" and action != "marg.mimic":
        notify(
            game,
            events,
            f"主持人为{actor['seat_id']}号完成了本阶段操作（内容不公开）。",
            alert=True,
        )
    sync_auto_advance(game)
    game["version"] += 1
    return events


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
    """没人在等的时候开始 5 秒倒计时；有人又卡住时撤销倒计时。"""
    if auto_advance_ready(game):
        game["public"].setdefault("auto_advance_at", time() + AUTO_ADVANCE_DELAY)
    else:
        game["public"].pop("auto_advance_at", None)


def run_auto_advance(game, now=None):
    """倒计时到点时替主持人推进；条件不成立或推进被拒时撤销倒计时。"""
    now = time() if now is None else now
    deadline = game["public"].get("auto_advance_at")
    if not deadline or deadline > now or game["status"] != "playing":
        return []
    events = []
    if auto_advance_ready(game):
        try:
            advance(game, events)
            sync_auto_advance(game)
        except GameError:
            game["public"].pop("auto_advance_at", None)
    else:
        game["public"].pop("auto_advance_at", None)
    game["version"] += 1
    return events


def expire_warnings(game, now=None):
    now = time() if now is None else now
    expired = [sid for sid, deadline in game["warnings"].items() if deadline <= now]
    if not expired or game["status"] != "playing":
        return []
    events = []
    for sid in expired:
        phase = game["phase"]
        hiro = hiro_dilemma(game, sid)
        if hiro:
            game["pending"] = [p for p in game["pending"] if p["id"] != hiro["id"]]
            if hiro.get("preview"):
                apply_damage(game, events, hiro["preview"], allow_reaction=False)
            notify(game, events, "警告到期，按预结算继续。", [sid], "希罗回溯")
        elif phase in {"night", "night_coco"} and sid not in game["night"]["confirmed"]:
            clear_seat_actions(game, sid)
            game["night"]["confirmed"].append(sid)
            if game["night"]["actors"].get(sid) == "noah":
                role_card(game, "noah")["states"]["paint_done"] = game["day"]
            unlock_coco(game, events)
        elif phase == "speech" and game["public"]["speaker"] == sid:
            speech_done(game, events)
        elif phase == "nomination" and sid in pending_nominators(game):
            game.setdefault("nomination_done", []).append(sid)
        elif phase == "voting":
            game["votes"][sid] = "abstain"
        elif phase == "execution":
            if sid not in game["execution_ready"]:
                game["execution_ready"].append(sid)
        if (
            game["public"]["balloon"]["status"] == "collecting"
            and sid in game["public"]["balloon"]["participants"]
        ):
            game["balloon_choices"][sid] = "skip"
        game["warnings"].pop(sid, None)
        notify(game, events, f"{sid}号警告时间已到，当前未完成操作按放弃处理。", alert=True)
        if game["status"] != "playing":
            # 过期结算（含热气球）可能已结束对局：不再写状态或处理其余席位。
            break
    balloon = game["public"]["balloon"]
    if balloon["status"] == "collecting" and set(balloon["participants"]).issubset(
        game["balloon_choices"]
    ):
        settle_balloon(game, events)
    game["deadline"] = min(game["warnings"].values(), default=None)
    sync_auto_advance(game)
    game["version"] += 1
    return events
