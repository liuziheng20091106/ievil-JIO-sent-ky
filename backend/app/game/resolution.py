"""Fixed intent/roll night resolution, damage previews, and linked exits."""

from copy import deepcopy
from random import SystemRandom

from .catalog import NIGHT_ABILITIES, ROLES
from .state import (
    check_winner,
    current,
    half_key,
    move_hanna,
    notify,
    owner,
    pending,
    poisoned,
    present,
    require,
    role_card,
    seat,
    uid,
)


def information(game, events, card, title, truth, image_id=None):
    sid = owner(game, card["id"])["id"]
    if poisoned(card):
        pending(
            game,
            "information",
            f"中毒信息裁定：{title}",
            seat_id=sid,
            truth=truth,
            image_id=image_id,
        )
    else:
        notify(game, events, truth, [sid], title, image_id)


def witch_information(game, events):
    if present(game, "coco") and role_card(game, "coco")["witch"]:
        information(
            game,
            events,
            role_card(game, "coco"),
            "魔女可可线索",
            "魔典顺序："
            + "、".join(ROLES[r]["name"] for r in game["codex"])
            + f"；艾玛{'已' if role_card(game, 'emma')['witch'] else '未'}魔女化。",
        )
    if present(game, "nanoka") and role_card(game, "nanoka")["witch"]:
        information(
            game,
            events,
            role_card(game, "nanoka"),
            "全员魔女化状态",
            "；".join(
                f"{ROLES[c['role_id']]['name']}：{'魔女' if c['witch'] else '普通'}"
                for c in game["cards"].values()
            ),
        )


def night_text(game, actions):
    return (
        "\n".join(
            f"{a['seat_id']}号：{NIGHT_ABILITIES[a['ability']][1]}"
            + (f"，目标{a['target_seat']}号" if a.get("target_seat") else "")
            + (
                "，破译排列：" + "、".join(ROLES[r]["name"] for r in a["guess"])
                if a.get("guess")
                else ""
            )
            + ("，画作：" + a.get("text", "") if a["ability"] == "paint" else "")
            for a in actions
        )
        or "其余玩家均未发动行动。"
    )


def begin_night(game, events):
    # actions imports this module; the ability list stays a local import to avoid a cycle.
    from .actions import night_abilities

    game["half"] = "night"
    game["phase"] = "night"
    game["night"] = {
        "actors": {s["id"]: current(game, s)["id"] for s in game["seats"] if current(game, s)},
        "actions": [],
        "confirmed": [],
        "locked": False,
        "preview": None,
        "reactions": [],
    }
    for sid, cid in game["night"]["actors"].items():
        if not night_abilities(game, game["cards"][cid]):
            game["night"]["confirmed"].append(sid)
            notify(
                game,
                events,
                "本夜你没有可执行的技能，已自动确认（未操作视为放弃）。",
                [sid],
            )
    witch_information(game, events)
    notify(game, events, "夜间行动开始，请选择行动后确认；也可放弃并确认。")
    # Everyone else auto-confirming can leave Coco as the only pending actor; nobody
    # would trigger the final confirmation step for her otherwise.
    unlock_coco(game, events)


def coco_seat(game):
    card = role_card(game, "coco")
    sid = owner(game, card["id"])["id"]
    return sid if card["witch"] and game["night"]["actors"].get(sid) == card["id"] else None


def unlock_coco(game, events):
    cs = coco_seat(game)
    others = set(game["night"]["actors"]) - ({cs} if cs else set())
    if cs and others.issubset(game["night"]["confirmed"]) and game["phase"] == "night":
        game["phase"] = "night_coco"
        information(
            game,
            events,
            role_card(game, "coco"),
            "其余夜间行动已锁定",
            night_text(game, game["night"]["actions"]),
        )
        for action in game["night"]["actions"]:
            if action.get("image_id"):
                information(
                    game,
                    events,
                    role_card(game, "coco"),
                    "夜间画作",
                    action.get("text", "画作"),
                    action["image_id"],
                )
        notify(game, events, "夜间行动进入最后确认步骤。")


def target_allowed(game, target_card_id):
    gaze = game.get("gaze")
    if gaze and gaze["night_day"] == game["day"]:
        return target_card_id in gaze["cards"]
    return True


def lock_night(game, events):
    night = game["night"]
    require(not night["locked"], "本夜已经锁定")
    require(set(night["actors"]).issubset(night["confirmed"]), "仍有玩家未确认；可先警告并等待30秒")
    night["locked"] = True
    rng = SystemRandom()
    for action in night["actions"]:
        card = game["cards"][action["card_id"]]
        ability = action["ability"]
        action["effective"] = ability == "knife" or not poisoned(card)
        action["title"] = f"{action['seat_id']}号 · {NIGHT_ABILITIES[ability][1]}"
        if ability == "shoot":
            require(card["uses"].get("bullets", 0) > 0, "子弹已经用尽")
            card["uses"]["bullets"] -= 1
            action["denominator"] = 3 if card["witch"] else 6
            action["roll"] = rng.randrange(action["denominator"]) + 1
            action["hit"] = action["roll"] == 1
        elif ability == "spear":
            action["denominator"] = 2
            action["roll"] = rng.randrange(2) + 1
            action["hit"] = action["roll"] == 1
        elif ability in {"extra_kill", "frame"}:
            card["uses"][ability] = True
        elif ability == "decode":
            card["uses"]["decode"] = card["uses"].get("decode", 0) + 1
            count = sum(a == b for a, b in zip(action["guess"], game["codex"]))
            action["correct"] = count
            information(
                game,
                events,
                card,
                "魔典破译",
                f"本次猜对{count}个位置；已发动{card['uses']['decode']}/2次。",
            )
        if not action["effective"] and ability != "decode":
            notify(game, events, "本次效果技能受中毒影响不生效。", [action["seat_id"]])
        if ability == "frame" and action["effective"]:
            card["states"]["framed_killer"] = action["target_card"]
    for photo in game["photos"]:
        if photo.get("allowed"):
            actions = [a for a in night["actions"] if a["seat_id"] == photo["recipient"]]
            notify(game, events, night_text(game, actions), [photo["sender"]], "照片授权的夜间行动")
            for a in actions:
                if a.get("image_id"):
                    notify(
                        game,
                        events,
                        a.get("text", "画作"),
                        [photo["sender"]],
                        "照片授权的画作",
                        a["image_id"],
                    )
    game["phase"] = "night_review"
    prepare_night_preview(game)


def damage_preview(game, attacks, protection=()):
    injured = {c["id"]: c["injured"] for c in game["cards"].values()}
    dead = {}
    guarded_seats = {sid for sid, key in game["half_exits"].items() if key == half_key(game)}
    for attack in attacks:
        cid = attack["target_card"]
        if cid not in game["cards"] or not game["cards"][cid]["alive"]:
            continue
        sid = owner(game, cid)["id"]
        if sid in guarded_seats or cid in dead:
            continue
        if current(game, sid)["id"] != cid and not attack.get("allow_lower"):
            continue
        protected = cid in protection or game["cards"][cid]["states"].get("protected")
        if attack.get("injury") or (protected and not attack.get("unconditional")):
            if injured[cid]:
                dead[cid] = {**attack, "seat_id": sid}
                guarded_seats.add(sid)
            else:
                injured[cid] = True
        else:
            dead[cid] = {**attack, "seat_id": sid}
            guarded_seats.add(sid)
    if (
        game["spiritual"]["sherry_bound"]
        and "hanna" in dead
        and dead["hanna"].get("cause") == "execution"
    ):
        sherry = role_card(game, "sherry")
        sid = owner(game, "sherry")["id"]
        if sherry["alive"] and sid not in guarded_seats:
            dead["sherry"] = {
                "target_card": "sherry",
                "seat_id": sid,
                "cause": "devotion",
                "source_card": "hanna",
                "unconditional": True,
            }
    return {"deaths": list(dead.values()), "injured": injured, "attacks": deepcopy(attacks)}


def swap_cards(game, swap):
    """米莉亚与被选席位交换上层角色牌，并记下本技能已使用。"""
    left, right = owner(game, "millia"), seat(game, swap["target_seat"])
    a, b = current(game, left), current(game, right)
    require(a and b and a["id"] == "millia", "换牌对象已改变，请先纠错")
    ia, ib = left["cards"].index(a["id"]), right["cards"].index(b["id"])
    left["cards"][ia], right["cards"][ib] = b["id"], a["id"]
    a["uses"]["swap"] = True


def prepare_night_preview(game):
    night = game["night"]
    preview, dead = night_damage(game)
    if (
        "millia" in dead
        and not role_card(game, "millia")["uses"].get("swap")
        and not poisoned(role_card(game, "millia"))
        and "millia" not in night["reactions"]
    ):
        action = next(
            (a for a in night["actions"] if a["ability"] == "swap" and a.get("effective")), None
        )
        if action:
            # 米莉亚自己选好了对象：直接换牌重算，不留主持人判定点。
            swap_cards(game, action)
            night["reactions"].append("millia")
            preview, dead = night_damage(game)
    night["preview"] = preview
    if (
        "hiro" in dead
        and not poisoned(role_card(game, "hiro"))
        and "hiro" not in night["reactions"]
    ):
        mode = "witch" if role_card(game, "hiro")["witch"] else "normal"
        if not game["spiritual"]["hiro_used"][mode]:
            pending(
                game,
                "hiro",
                "希罗庇护后仍会死亡：裁定是否回溯及对应时间点",
                mode=mode,
                seat_id=owner(game, "hiro")["id"],
                expected_day=game["day"] - 1,
                expected_phase="night",
            )
            night["reactions"].append("hiro")


def night_damage(game):
    attacks, protection = [], []
    night = game["night"]
    for a in night["actions"]:
        if not a.get("effective"):
            continue
        ability = a["ability"]
        target = a.get("target_card")
        if a.get("follow_seat") and a.get("target_seat"):
            now = current(game, a["target_seat"])
            target = now["id"] if now else None
        if ability == "protect" and target:
            protection.append(target)
        elif ability in {"knife", "extra_kill", "shoot", "spear"} and target and a.get("hit", True):
            attacks.append({"target_card": target, "source_card": a["card_id"], "cause": ability})
        elif ability == "massacre":
            attacks.extend(
                {"target_card": c["id"], "source_card": a["card_id"], "cause": ability}
                for c in game["cards"].values()
                if c["alive"] and c["id"] != a["card_id"] and target_allowed(game, c["id"])
            )
    attacks.extend(night.get("extra_attacks", []))
    preview = damage_preview(game, attacks, protection)
    return preview, {d["target_card"] for d in preview["deaths"]}


def death_batch(game, events, preview):
    for cid, injured in preview["injured"].items():
        game["cards"][cid]["injured"] = injured
    killed = []
    for death in preview["deaths"]:
        cid = death["target_card"]
        card = game["cards"][cid]
        s = owner(game, cid)
        if not card["alive"] or game["half_exits"].get(s["id"]) == half_key(game):
            continue
        card["alive"] = False
        if cid in {"sherry", "hanna"} and game.get("day_binding"):
            game["day_binding"]["intact"] = False
        game["half_exits"][s["id"]] = half_key(game)
        record = {"id": uid(), "day": game["day"], "half": game["half"], **deepcopy(death)}
        game["deaths"].append(record)
        killed.append(record)
        source = death.get("source_card")
        if source:
            game["cards"][source]["states"].setdefault("kills", []).append(
                {"card_id": cid, "day": game["day"]}
            )
        if cid == "sherry" and game["spiritual"]["sherry_bound"]:
            move_hanna(game, -3)
        suffix = (
            "，死于13水" if death.get("cause") == "water" and not death.get("hide_cause") else ""
        )
        notify(game, events, f"{s['id']}号玩家一张角色牌出局{suffix}。", alert=True)
        lower = current(game, s)
        if lower:
            s["avatar_role_id"] = lower["role_id"]
            text = f"下层角色{ROLES[lower['role_id']]['name']}已登场。"
            if lower["id"] == "honoka":
                text += "你可以选择一次示人角色。"
            notify(game, events, text, [s["id"]], "下层登场")
            pending(
                game,
                "lower_entry",
                f"{s['id']}号下层登场：裁定本阶段是否立即可行动",
                seat_id=s["id"],
                card_id=lower["id"],
            )
        if game["half"] == "night":
            pending(
                game,
                "suspects",
                f"{s['id']}号夜间死者：填写三名疑似凶手（含真凶与汉娜）",
                seat_id=s["id"],
                death_id=record["id"],
                victim=cid,
                source_card=source,
            )
    if killed:
        check_winner(game)
    return killed


def revive(game, events, card_id, puppet=None):
    card = game["cards"][card_id]
    require(not card["alive"], "该牌尚未出局")
    card["alive"] = True
    card["injured"] = False
    if puppet:
        card["states"]["puppet"] = puppet
    if card_id == "sherry" and game["spiritual"]["sherry_bound"]:
        move_hanna(game, 2)
    owner_seat = owner(game, card_id)
    now = current(game, owner_seat)
    if now:
        owner_seat["avatar_role_id"] = now["role_id"]
    notify(game, events, f"{owner_seat['id']}号玩家一张角色牌复活。", alert=True)
    check_winner(game)
