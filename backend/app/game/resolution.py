"""Fixed intent/roll night resolution, damage previews, and linked exits."""

from copy import deepcopy
from random import SystemRandom

from .catalog import NIGHT_ABILITIES, ROLES
from .state import (
    card_actionable,
    fallen_upper_role,
    check_winner,
    current,
    effect_effective,
    half_key,
    hiro_rewind,
    log_event,
    notify,
    owner,
    pending,
    present,
    require,
    role_card,
    seat,
    uid,
)


def information(game, events, card, title, truth, false_text, image_id=None):
    sid = owner(game, card["id"])["id"]
    text = truth if effect_effective(game, events, card, f"信息：{title}") else false_text
    notify(game, events, text, [sid], title, image_id)

def witch_information(game, events):
    if present(game, "coco") and role_card(game, "coco")["witch"]:
        codex = game["codex"]
        information(
            game,
            events,
            role_card(game, "coco"),
            "魔女可可线索",
            "魔典顺序：" + "、".join(ROLES[r]["name"] for r in codex),
            "魔典顺序：" + "、".join(ROLES[r]["name"] for r in codex[-1:] + codex[:-1]),
        )


def night_text(game, actions):
    return (
        "\n".join(
            f"{a['seat_id']}号：{NIGHT_ABILITIES[a['ability']][1]}"
            + (f"，目标{a['target_seat']}号" if a.get("target_seat") else "")
            for a in actions
        )
        or "其余玩家均未发动行动。"
    )


def sync_night_confirmations(game, events):
    """把「本夜没有任何可提交行动」的席位补进已确认集合。

    傀儡化、失去技能或出局都可能在一夜之间发生（主持人裁定、魔女化、复活的
    傀儡牌），这些席位既不会拿到行动也不该留下阻塞待办，因此统一在这里对齐。
    """
    if game["status"] != "playing" or game["phase"] not in {"night", "night_coco"}:
        return
    # actions imports this module; the ability list stays a local import to avoid a cycle.
    from .actions import night_abilities

    night = game["night"]

    def drivable(cid):
        card = game["cards"].get(cid)
        return bool(card) and card_actionable(game, card) and night_abilities(game, card)

    for sid, cid in night["actors"].items():
        if sid in night["confirmed"] or drivable(cid):
            continue
        night["confirmed"].append(sid)
        notify(game, events, "本夜你没有可执行的技能，已自动确认（未操作视为放弃）。", [sid])


def begin_night(game, events):
    game["half"] = "night"
    game["phase"] = "night"
    # 上一夜未使用的13水过期收回；米莉亚的换血目标单独持久保存，直到下次有效换血覆盖。
    game["water"] = {"holders": []}
    game["night"] = {
        "actors": {s["id"]: current(game, s)["id"] for s in game["seats"] if current(game, s)},
        "actions": [],
        "confirmed": [],
        "locked": False,
        "preview": None,
        "reactions": [],
    }
    # 用 card_actionable：傀儡牌由控制它的梅露露代行，不能当「本夜无事可做」自动确认掉。
    sync_night_confirmations(game, events)
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
            "中毒幻觉：未辨识到有效夜间行动",
        )
        notify(game, events, "夜间行动进入最后确认步骤。")


def target_allowed(game, target_card_id):
    return True


def treasure_protected(game, target_card_id):
    """这张牌当天是否受寻宝保护：魔女刀、蕾雅长矛与提名都不能选中它。"""
    return game["cards"][target_card_id]["states"].get("treasure_protected_day") == game["day"]

def lock_night(game, events):
    night = game["night"]
    require(not night["locked"], "本夜已经锁定")
    require(set(night["actors"]).issubset(night["confirmed"]), "仍有玩家未确认；可先警告并等待30秒")
    night["locked"] = True
    for action in night["actions"]:
        card = game["cards"][action["card_id"]]
        ability = action["ability"]
        action["title"] = f"{action['seat_id']}号 · {NIGHT_ABILITIES[ability][1]}"
        if action.get("resolved"):
            continue
        if ability == "witch_scan":
            cards = list(game["cards"].values())
            information(
                game,
                events,
                card,
                "全员魔女化状态",
                "；".join(f"{ROLES[c['role_id']]['name']}：{'魔女' if c['witch'] else '普通'}" for c in cards),
                "；".join(f"{ROLES[c['role_id']]['name']}：{'普通' if c['witch'] else '魔女'}" for c in cards),
            )
            action["effective"] = True
            continue
        action["effective"] = effect_effective(game, events, card, NIGHT_ABILITIES[ability][1])
        if ability in {"extra_kill", "rain", "scapegoat"}:
            card["uses"][ability] = True
        if ability == "rain" and action["effective"]:
            night["rain"] = True
        if ability == "scapegoat" and action["effective"]:
            card["states"]["display_killer"] = action["target_card"]
        if ability == "arisa_injure" and action["effective"]:
            seats = game["seats"]
            index = seats.index(owner(game, card["id"]))
            action["injuries"] = []
            for neighbor in (seats[(index - 1) % len(seats)], seats[(index + 1) % len(seats)]):
                target = current(game, neighbor)
                roll = SystemRandom().randrange(2)
                injured = roll == 0 and target is not None
                if injured:
                    action["injuries"].append(target["id"])
                log_event(
                    game,
                    "roll",
                    f"亚里沙令{neighbor['id']}号邻座负伤：骰值{roll}，{'发生' if injured else '未发生'}。",
                )
    for photo in game["photos"]:
        if photo.get("allowed"):
            actions = [a for a in night["actions"] if a["seat_id"] == photo["target"]]
            notify(game, events, night_text(game, actions), [photo["sender"]], "信物授权的夜间行动")
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
        if attack.get("once_injury"):
            injured[cid] = True
        elif attack.get("injury") or (protected and not attack.get("unconditional")):
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


def millia_swap_effective(game):
    """换血是否生效：每个半天只骰一次中毒判定，重算预结算不会重复掷骰。"""
    swap = game.get("millia_swap")
    if not swap or not swap.get("seat"):
        return None
    key = half_key(game)
    if swap.get("key") != key:
        swap["key"] = key
        swap["effective"] = effect_effective(
            game, [], role_card(game, "millia"), "代替死亡"
        )
    return swap if swap["effective"] else None


def millia_substitute(game, attacks):
    """米莉亚替死：指向当前换血目标的普通死亡改由米莉亚牌承担。

    换血目标存在状态里并一直生效（跨白天），直到下一次有效换血覆盖它；
    处刑、殉情与质疑整席出局显式不走替死。
    """
    at_night = game["phase"] in {"night", "night_coco", "night_review"}
    night = game["night"]
    swap = millia_swap_effective(game)
    millia_card = role_card(game, "millia")
    if (
        swap is None
        or not millia_card["alive"]
        or (at_night and "millia" in night["reactions"])
    ):
        return attacks
    target = current(game, seat(game, swap["seat"]))
    if not target:
        return attacks
    substituted = False
    rewritten = []
    for attack in attacks:
        if (
            attack["target_card"] == target["id"]
            and not substituted
            and not attack.get("once_injury")
            and attack.get("cause") not in {"devotion", "execution", "shoot", "challenge"}
        ):
            attack = {**attack, "target_card": "millia"}
            substituted = True
        rewritten.append(attack)
    if substituted and at_night:
        night["reactions"].append("millia")
    return rewritten


def day_damage_preview(game, attacks, protection=()):
    """白天的非处刑伤害：先让米莉亚替死，再按标准规则预结算。

    处刑与质疑整席出局不走这里，因此显式绕过替死。
    """
    return damage_preview(game, millia_substitute(game, attacks), protection)


def prepare_night_preview(game):
    night = game["night"]
    night["reactions"] = [r for r in night["reactions"] if r != "millia"]
    preview, dead = night_damage(game)
    night["preview"] = preview
    # 夜间预结算里希罗死亡时立即回溯到前一天顺序发言，不放主持人待办。
    if "hiro" in dead and effect_effective(game, [], role_card(game, "hiro"), "时间回溯"):
        hiro = role_card(game, "hiro")
        if not game["spiritual"]["hiro_used"]["witch" if hiro["witch"] else "normal"]:
            hiro_rewind(game, [], "night")


def night_damage(game):
    attacks, protection = [], []
    night = game["night"]
    for action in night["actions"]:
        if not action.get("effective"):
            continue
        ability = action["ability"]
        target = action.get("target_card")
        if action.get("follow_seat") and action.get("target_seat"):
            now = current(game, action["target_seat"])
            target = now["id"] if now else None
        if ability == "protect" and target:
            protection.append(target)
        elif ability in {"knife", "extra_kill"} and target:
            attacks.append({"target_card": target, "source_card": action["card_id"], "cause": ability})
        elif ability == "massacre":
            attacks.extend(
                {"target_card": card["id"], "source_card": action["card_id"], "cause": ability}
                for card in game["cards"].values()
                if card["alive"] and card["id"] != action["card_id"]
            )
        elif ability == "arisa_injure":
            attacks.extend(
                {"target_card": target_id, "source_card": action["card_id"], "cause": ability, "once_injury": True}
                for target_id in action.get("injuries", [])
            )
    love = game.get("marg_love")
    if love and present(game, "marg"):
        loved = seat(game, love["seat_id"])
        if not current(game, loved):
            loved = owner(game, "marg")
            love["seat_id"] = loved["id"]
            love["self"] = True
        target = current(game, loved)
        if target:
            attacks.append({"target_card": target["id"], "source_card": "marg", "cause": "love", "once_injury": True})
    attacks.extend(night.get("extra_attacks", []))
    attacks = millia_substitute(game, attacks)
    preview = damage_preview(game, attacks, protection)
    return preview, {death["target_card"] for death in preview["deaths"]}


def eliminate_seat(game, events, seat, notice):
    """整席出局：两张牌直接作废，不触发出局流程（亡语、回溯、证物、疑似凶手等）。"""
    for card_id in seat["cards"]:
        game["cards"][card_id]["alive"] = False
        game["deaths"].append(
            {
                "id": uid(),
                "day": game["day"],
                "half": game["half"],
                "seat_id": seat["id"],
                "target_card": card_id,
                "cause": "challenge",
            }
        )
    if set(seat["cards"]) & {"sherry", "hanna"} and game.get("day_binding"):
        game["day_binding"]["intact"] = False
    game["half_exits"][seat["id"]] = half_key(game)
    notify(game, events, notice, alert=True)
    check_winner(game)


def publish_witness(game, events, item, suspects, honoka_role="honoka"):
    """向死者发送四人疑似凶手名单，并记录本夜已发目击供复活撤销。"""
    shown = [honoka_role if role == "honoka" else role for role in suspects]
    text = "四名疑似凶手：" + "、".join(ROLES[role]["name"] for role in shown)
    notify(game, events, text, [item["seat_id"]], "夜间目击名单")
    game["witness"] = {
        "day": game["day"],
        "seat_id": item["seat_id"],
        "death_id": item.get("death_id"),
        "text": text,
    }
    victim_seat = seat(game, item["seat_id"])
    if not current(game, victim_seat):
        game["cards"][item["victim"]]["states"]["evidence_allowed"] = True


def witness_suspects(game, victim_role):
    """固定的四人目击名单：真凶、在场的梅露露、在场的汉娜，余位随机补齐。"""
    fixed = []
    if victim_role:
        fixed.append(victim_role)
    for role in ("meruru", "hanna"):
        if present(game, role):
            fixed.append(role)
    suspects = list(dict.fromkeys(fixed))[:4]
    pool = [role for role in ROLES if role not in suspects]
    SystemRandom().shuffle(pool)
    return suspects + pool[: 4 - len(suspects)]


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
        before = {
            "seat_id": s["id"],
            "avatar_role_id": s["avatar_role_id"],
            "previous_role_id": fallen_upper_role(game, s),
            "alive": current(game, s) is not None,
        }
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
        if game["half"] == "night" and game["night"].get("rain") and source:
            shown_source = game["cards"][source]["states"].get("display_killer", source)
            source_seat = owner(game, shown_source)
            if source_seat["id"] != s["id"]:
                greater = int(source_seat["id"]) > int(s["id"])
                if source == "hanna":
                    greater = not greater
                notify(
                    game,
                    events,
                    f"雨夜脚印：凶手座位号{'大于' if greater else '小于'}死者座位号。",
                    title="雨夜脚印",
                )
        hidden = bool(death.get("hide_cause"))
        suffixed = death.get("cause") == "water" and not hidden
        notice = (
            f"{s['id']}号玩家被13水毒杀。"
            if suffixed
            else f"{s['id']}号玩家一张角色牌出局。"
        )
        record["notice"] = notice
        cause_label = NIGHT_ABILITIES.get(death.get("cause"), (None, death.get("cause") or ""))[1]
        src = death.get("source_card")
        src_label = ROLES.get(src, {}).get("name", src) if src else ""
        detail = f"（{cause_label}" + (f"·{src_label}" if src_label else "") + ")" if cause_label else ""
        log_event(game, "death", f"{s['id']}号的{ROLES[cid]['name']}出局{detail}")
        if game["half"] == "night":
            # 夜间出局连同头像一起压到第二天白天再公示，夜间阶段不泄露
            game["queued_notices"].append(notice)
            game["queued_reveals"].append(before)
            if suffixed:
                # 未隐藏的13水死亡：直接构造并随机排序四人目击，无需主持人待办。
                publish_witness(
                    game,
                    events,
                    {"seat_id": s["id"], "victim": cid, "death_id": record["id"]},
                    witness_suspects(game, src),
                )
            else:
                pending(
                    game,
                    "suspects",
                    f"{s['id']}号夜间死者：填写四名疑似凶手（真凶、汉娜及额外两人）",
                    seat_id=s["id"],
                    death_id=record["id"],
                    victim=cid,
                    source_card=source,
                )
        else:
            notify(game, events, notice, alert=True)
            # 白天死亡当场公示，下层牌立即登场并取得本阶段的行动。
            lower = current(game, s)
            if lower:
                s["avatar_role_id"] = lower["role_id"]
                text = f"下层角色{ROLES[lower['role_id']]['name']}已登场。"
                if lower["id"] == "honoka":
                    text += "你可以选择一次示人角色。"
                notify(game, events, text, [s["id"]], "下层登场")
        if card["states"].pop("puppet", None):
            # 傀儡当前牌出局：控制关系解除；该席下层牌仍存活则本人重新回到游戏。
            card["states"].pop("no_ability", None)
            if current(game, s):
                notify(
                    game,
                    events,
                    "你已重新回到游戏，恢复普通玩家权限。",
                    [s["id"]],
                    "傀儡解除",
                )
    if killed:
        check_winner(game)
    return killed


def revoke_death(game, events, death):
    """梅露露复活：撤销该次死亡在公共记录、待办与已发目击里的全部痕迹。"""
    cid, sid = death["target_card"], death["seat_id"]
    game["deaths"] = [item for item in game["deaths"] if item["id"] != death["id"]]
    game["queued_notices"] = [
        notice for notice in game["queued_notices"] if notice != death.get("notice")
    ]
    game["queued_reveals"] = [item for item in game["queued_reveals"] if item["seat_id"] != sid]
    game["pending"] = [
        item
        for item in game["pending"]
        if item.get("death_id") != death["id"] and not (item["kind"] == "suspects" and item.get("victim") == cid)
    ]
    if game.get("witness") and game["witness"].get("death_id") == death["id"]:
        game["witness"] = None
    if game["half_exits"].get(sid) == half_key(game):
        del game["half_exits"][sid]
    check_winner(game)


def revive(game, events, card_id, puppet=None):
    card = game["cards"][card_id]
    require(not card["alive"], "该牌尚未出局")
    card["alive"] = True
    card["injured"] = False
    if puppet:
        card["states"]["puppet"] = puppet
        card["states"]["no_ability"] = True
    owner_seat = owner(game, card_id)
    now = current(game, owner_seat)
    if now:
        owner_seat["avatar_role_id"] = now["role_id"]
    notify(game, events, f"{owner_seat['id']}号玩家一张角色牌复活。", alert=True)
    check_winner(game)
