"""Game commands and phase flow; callers commit a copied state atomically."""

from copy import deepcopy
from random import SystemRandom
from time import time

from .actions import actions_for, can_day_ability, night_abilities
from .catalog import DAY_ABILITIES, PHASES, ROLES
from .resolution import (
    begin_night,
    coco_seat,
    damage_preview,
    death_batch,
    information,
    lock_night,
    prepare_night_preview,
    revive,
    target_allowed,
    unlock_coco,
)
from .state import (
    GameError,
    audience,
    check_winner,
    clear_seat_actions,
    current,
    eligible_voters,
    finish,
    next_nominator,
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


def apply_damage(game, events, preview, allow_reaction=True):
    millia = role_card(game, "millia")
    swap = next(
        (a for a in game["night"]["actions"] if a["ability"] == "swap" and a.get("effective")), None
    )
    if (
        allow_reaction
        and swap
        and not millia["uses"].get("swap")
        and not poisoned(millia)
        and any(d["target_card"] == "millia" for d in preview["deaths"])
    ):
        pending(
            game,
            "millia",
            "米莉亚即将死亡：裁定交换后的目标跟随方式",
            seat_id=owner(game, "millia")["id"],
            target_seat=swap["target_seat"],
            preview=preview,
        )
        return
    hiro = role_card(game, "hiro")
    mode = "witch" if hiro["witch"] else "normal"
    if (
        allow_reaction
        and not poisoned(hiro)
        and not game["spiritual"]["hiro_used"][mode]
        and any(d["target_card"] == "hiro" for d in preview["deaths"])
    ):
        pending(
            game,
            "hiro",
            "希罗即将出局：裁定回溯或按预结算继续",
            mode=mode,
            seat_id=owner(game, "hiro")["id"],
            expected_day=game["day"] - 1,
            expected_phase=game["phase"],
            preview=preview,
        )
    else:
        death_batch(game, events, preview)


def open_balloon(game, events, organizer, participants):
    balloon = game["public"]["balloon"]
    require(balloon["day"] != game["day"], "本白天已组织过热气球")
    require(
        1 <= len(participants) <= 4 and len(set(participants)) == len(participants),
        "热气球需要1至4名不重复参加者",
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
    notify(game, events, f"热气球开始制作，参加席位：{'、'.join(participants)}。")


def settle_balloon(game, events):
    balloon = game["public"]["balloon"]
    require(
        set(balloon["participants"]).issubset(game["balloon_choices"]),
        "热气球仍有人未确认，可先警告",
    )
    choices = game["balloon_choices"].values()
    balloon["progress"] = (
        0 if "break" in choices else balloon["progress"] + sum(v == "make" for v in choices)
    )
    balloon["status"] = "complete"
    notify(game, events, f"热气球当前进度：{balloon['progress']}/13。")
    if (
        balloon["progress"] >= 13
        and present(game, "arisa")
        and any(c["alive"] and c["witch"] for c in game["cards"].values())
    ):
        finish(game, events, "good", "热气球达到13并起飞；安安强制落败。", balloon=True)


def speech_done(game):
    public = game["public"]
    if public.get("interrupted_speaker"):
        public["speaker"] = public.pop("interrupted_speaker")
        return
    order = public["speech_order"]
    now = public["speaker"]
    index = order.index(now) + 1 if now in order else 0
    public["speaker"] = order[index] if index < len(order) else None


def brainwash_targets(game):
    active = game["brainwash"]
    if "annan" in active and "marg" in active:
        return set()
    return set(active.values())


def open_vote(game, events):
    index = len(game["vote_rounds"])
    if index >= len(game["nominations"]):
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
    game["votes"] = {}
    nominee = game["nominations"][index]
    game["public"]["votes"] = {
        "candidate": nominee["seat_id"],
        "round": index + 1,
        "total": len(game["nominations"]),
        "results": deepcopy(game["vote_rounds"]),
    }
    notify(
        game,
        events,
        f"开始对{nominee['seat_id']}号候选投票；严格超过有投票权存活玩家的一半方可处决。",
    )


def close_vote(game, events):
    voters = eligible_voters(game)
    require(all(s["id"] in game["votes"] for s in voters), "仍有玩家未投票，可先警告")
    forced = brainwash_targets(game)
    nominee = game["nominations"][len(game["vote_rounds"])]
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
        order = game["public"]["speech_order"] or list(
            dict.fromkeys(dead_first + [s["id"] for s in game["seats"]])
        )
        game["public"]["speech_order"] = order
        game["public"]["speaker"] = order[0] if order else None
        game["brainwash"] = {}
        game["nominations"] = []
        game["vote_rounds"] = []
        game["execution"] = []
        game["balloon_votes"] = {}
    elif phase == "speech":
        require(game["public"]["speaker"] is None, "仍有顺序发言未完成，请玩家确认或警告超时")
        game["phase"] = "discussion"
    elif phase == "discussion":
        game["phase"] = "balloon"
    elif phase == "balloon":
        if game["public"]["balloon"]["status"] == "collecting":
            settle_balloon(game, events)
        if game["status"] != "ended":
            game["phase"] = "nomination"
            game["nomination_done"] = []
    elif phase == "nomination":
        require(next_nominator(game) is None, "仍有玩家未依次提名或放弃，可警告后等待30秒")
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
        if present(game, "nanoka"):
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
        notify(game, events, f"{target}号进入本轮处决名单。")
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
        open_balloon(game, events, sid, data["participants"])
    declaration["executed"] = True


def resolve_pending(game, events, data):
    item = next(p for p in game["pending"] if p["id"] == data["pending_id"])
    kind = item["kind"]
    if kind == "information":
        notify(
            game, events, data["text"], [item["seat_id"]], "主持人裁定信息", item.get("image_id")
        )
    elif kind == "millia":
        left, right = seat(game, item["seat_id"]), seat(game, item["target_seat"])
        target_seats = [
            owner(game, attack["target_card"])["id"]
            for attack in item.get("preview", {}).get("attacks", [])
        ]
        a, b = current(game, left), current(game, right)
        require(a and b and a["id"] == "millia", "换牌对象已改变，请先纠错")
        ia, ib = left["cards"].index(a["id"]), right["cards"].index(b["id"])
        left["cards"][ia], right["cards"][ib] = b["id"], a["id"]
        a["uses"]["swap"] = True
        for action in game["night"]["actions"]:
            action["follow_seat"] = data["follow"] == "seat"
        notify(game, events, "米莉亚临死交换已生效。", [left["id"], right["id"]], "角色交换")
        if item.get("preview"):
            attacks = deepcopy(item["preview"]["attacks"])
            if data["follow"] == "seat":
                for attack, sid in zip(attacks, target_seats):
                    target = current(game, sid)
                    if target:
                        attack["target_card"] = target["id"]
            apply_damage(game, events, damage_preview(game, attacks))
        else:
            prepare_night_preview(game)
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
    elif kind == "challenge":
        require(data["confirm"] is True, "请确认质疑结算")
        declaration = next(d for d in game["declarations"] if d["id"] == item["declaration_id"])
        require(declaration["status"] == "open", "该技能声明已结束")
        if declaration["fake"]:
            declaration["status"] = "stopped"
            game["pending"] = [
                p for p in game["pending"] if p.get("declaration_id") != declaration["id"]
            ]
            notify(
                game, events, f"{item['seat_id']}号质疑成功：尚未完成的技能停止，已执行部分不撤销。"
            )
        else:
            s = seat(game, item["seat_id"])
            if s["occupant_id"] not in game["spiritual"]["personal_losses"]:
                game["spiritual"]["personal_losses"].append(s["occupant_id"])
            c = current(game, s)
            if c:
                apply_damage(
                    game,
                    events,
                    damage_preview(
                        game,
                        [{"target_card": c["id"], "cause": "challenge", "unconditional": True}],
                    ),
                )
            notify(game, events, f"{item['seat_id']}号质疑失败，因犯规出局且本局个人判负。")
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
    elif kind == "balloon_organize":
        if data.get("allow"):
            open_balloon(game, events, "good_vote", data["participants"])
        else:
            game["balloon_votes"] = {}
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
        require(
            all(s["occupant_id"] and s["ready"] for s in game["seats"]),
            "需要7名玩家全部入座、确认上下牌并准备",
        )
        game["status"] = "playing"
        game["phase"] = "witch"
        honoka = role_card(game, "honoka")
        sid = owner(game, "honoka")["id"]
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
        game["public"]["speech_order"] = list(data["order"])
        if game["phase"] == "speech":
            game["public"]["speaker"] = data["order"][0]
        notify(game, events, "发言顺序：" + " → ".join(data["order"]))
    elif action == "host.warn":
        sid = data["seat_id"]
        require(sid not in game["warnings"], "该玩家已经处于30秒警告倒计时")
        phase = game["phase"]
        outstanding = (
            phase in {"night", "night_coco"}
            and sid in game["night"]["actors"]
            and sid not in game["night"]["confirmed"]
            and (sid != coco_seat(game) or phase == "night_coco")
        )
        outstanding |= phase == "speech" and game["public"]["speaker"] == sid
        outstanding |= phase == "nomination" and next_nominator(game) == sid
        outstanding |= (
            phase == "voting"
            and seat(game, sid) in eligible_voters(game)
            and sid not in game["votes"]
        )
        outstanding |= (
            phase == "execution"
            and any(owner(game, cid)["id"] == sid for cid in game["execution"])
            and sid not in game["execution_ready"]
        )
        outstanding |= (
            game["public"]["balloon"]["status"] == "collecting"
            and sid in game["public"]["balloon"]["participants"]
            and sid not in game["balloon_choices"]
        )
        require(outstanding, "该席位当前没有可超时的待确认操作")
        game["warnings"][sid] = time() + 30
        game["deadline"] = min(game["warnings"].values())
        notify(game, events, f"{sid}号玩家请在30秒内完成当前操作，逾期视为未操作。")
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


def player_command(game, actor, events, action, data):
    s = player_seat(game, actor)
    sid = s["id"]
    card = current(game, s)
    if action == "lobby.order":
        s["cards"] = [data["top"]] + [cid for cid in s["cards"] if cid != data["top"]]
        s["ready"] = False
    elif action == "lobby.ready":
        s["ready"] = not s["ready"]
    elif action == "player.profile":
        require(1 <= len(data["name"].strip()) <= 30, "公开称呼需为1至30字")
        s["name"] = data["name"].strip()
        s["avatar_role_id"] = data.get("avatar") or None
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
        fake = card["id"] == "honoka" and DAY_ABILITIES[ability][0] != "honoka"
        require(fake or can_day_ability(game, card, ability), "此时不能声明该技能")
        d = {
            "id": uid(),
            "day": game["day"],
            "seat_id": sid,
            "card_id": card["id"],
            "ability": ability,
            "fake": fake,
            "data": deepcopy(data),
            "status": "open",
            "executed": False,
        }
        game["declarations"].append(d)
        pending(
            game,
            "declaration",
            f"{sid}号声明{DAY_ABILITIES[ability][1]}：{'伪装，按主持人裁定执行' if fake else '真实技能'}",
            declaration_id=d["id"],
        )
        sync_declarations(game)
        notify(game, events, f"{sid}号声明发动「{DAY_ABILITIES[ability][1]}」，其他玩家可质疑。")
    elif action == "day.challenge":
        d = next(d for d in game["declarations"] if d["id"] == data["declaration_id"])
        require(d["seat_id"] != sid, "不可质疑自己")
        pending(
            game,
            "challenge",
            f"{sid}号质疑{d['seat_id']}号声明，主持人确认按真伪结算",
            declaration_id=d["id"],
            seat_id=sid,
        )
        notify(game, events, f"{sid}号质疑{d['seat_id']}号的技能声明，等待主持人结算。")
    elif action == "honoka.disguise":
        s["avatar_role_id"] = data["role"]
        notify(game, events, f"{sid}号示人为{ROLES[data['role']]['name']}。")
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
        speech_done(game)
    elif action == "vote.nominate":
        target = current(game, data["target"])
        require(
            not any(n["card_id"] == target["id"] for n in game["nominations"]), "该角色已经被提名"
        )
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
        target = game["nominations"][len(game["vote_rounds"])]["card_id"]
        require(
            not (
                data["choice"] == "yes"
                and card["id"] == "sherry"
                and game["spiritual"]["sherry_bound"]
                and target == "hanna"
            ),
            "雪莉不能同意处决绑定的汉娜",
        )
        game["votes"][sid] = "abstain" if sid in brainwash_targets(game) else data["choice"]
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
        )
    elif action == "execution.confirm":
        game["execution_ready"].append(sid)
    elif action == "balloon.choose":
        game["balloon_choices"][sid] = data["choice"]
        if set(game["public"]["balloon"]["participants"]).issubset(game["balloon_choices"]):
            settle_balloon(game, events)
    elif action == "balloon.organize_vote":
        game["balloon_votes"][sid] = bool(data.get("agree"))
        if not any(p["kind"] == "balloon_organize" for p in game["pending"]):
            pending(game, "balloon_organize", "亚里沙不在场：裁定好人组织投票并指定参加者")
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
    if sid in game["warnings"] and action in {
        "night.confirm",
        "speech.done",
        "vote.nominate",
        "vote.pass",
        "vote.cast",
        "execution.shoot",
        "execution.confirm",
        "balloon.choose",
    }:
        del game["warnings"][sid]
        game["deadline"] = min(game["warnings"].values(), default=None)


def apply_command(game, actor, action, payload):
    require(game["status"] != "ended", "对局已结束，不能再操作")
    validate_command(game, actor, action, payload)
    events = []
    if actor["kind"] == "host":
        host_command(game, events, action, payload)
    else:
        player_command(game, actor, events, action, payload)
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
        if phase in {"night", "night_coco"} and sid not in game["night"]["confirmed"]:
            clear_seat_actions(game, sid)
            game["night"]["confirmed"].append(sid)
            if game["night"]["actors"].get(sid) == "noah":
                role_card(game, "noah")["states"]["paint_done"] = game["day"]
            unlock_coco(game, events)
        elif phase == "speech" and game["public"]["speaker"] == sid:
            speech_done(game)
        elif phase == "nomination" and next_nominator(game) == sid:
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
        notify(game, events, f"{sid}号警告时间已到，当前未完成操作按放弃处理。")
    balloon = game["public"]["balloon"]
    if balloon["status"] == "collecting" and set(balloon["participants"]).issubset(
        game["balloon_choices"]
    ):
        settle_balloon(game, events)
    game["deadline"] = min(game["warnings"].values(), default=None)
    game["version"] += 1
    return events
