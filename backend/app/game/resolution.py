"""Fixed intent/roll night resolution, damage previews, and linked exits."""

from copy import deepcopy
from random import SystemRandom

from . import plugins
from .external_plugins import emma_treasure
from .roles import annan, arisa, emma, hanna, hiro, honoka, marg, millia, nanoka, noah, sherry
from .roles.coco import unlock_coco, witch_information
from .roles.marg import loved_card_id

from .catalog import NIGHT_ABILITIES, ROLES
from .state import (
    card_actionable,
    death_card_entry,
    death_card_payload,
    fallen_upper_role,
    check_winner,
    current,
    effect_effective,
    half_key,
    log_event,
    notify,
    owner,
    passive_card_payload,
    pending,
    present,
    protection_active,
    release_puppet,
    require,
    seat,
    start_phase,
    uid,
)


def information(game, events, card, title, truth, false_text, image_id=None, payload=None):
    sid = owner(game, card["id"])["id"]
    # 中毒只影响这条信息是真是假，不告诉本人掷骰结果（主持人日志里仍有中毒骰）。
    # payload 只给被动技能的播报卡片用：调用方负责把结果写进载荷（必须与 text 同源，
    # 否则卡片与文本会一个真一个假），收件人仍由这里的 [sid] 决定。
    effective = effect_effective(game, card, f"信息：{title}")
    text = truth if effective else false_text
    if payload is not None:
        payload = {**payload, "effect": text}
    notify(game, events, text, [sid], title, image_id, payload=payload)


def night_text(game, actions):
    """可可看到的夜间行动清单。

    除玩家提交的行动外，还要带上 `extra_attacks` 里的额外攻击（主持人伤害、13 水），
    否则可可的「查看其他全部夜间行动」与照片授权报告都会漏掉这两类。
    """
    lines = [
        f"{a['seat_id']}号：{NIGHT_ABILITIES[a['ability']][1]}"
        + (f"，目标{a['target_seat']}号" if a.get("target_seat") else "")
        for a in actions
    ]
    for attack in (game.get("night") or {}).get("extra_attacks", []):
        source = game["cards"].get(attack.get("source_card"))
        target = game["cards"].get(attack.get("target_card"))
        who = f"{owner(game, source['id'])['id']}号" if source else "主持人"
        where = f"，目标{owner(game, target['id'])['id']}号" if target else ""
        label = {"water": "13水", "host": "主持人伤害"}.get(
            attack.get("cause"), attack.get("cause") or ""
        )
        lines.append(f"{who}：{label}{where}")
    return "\n".join(lines) or "其余玩家均未发动行动。"


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
    previous = game["phase"]
    game["half"] = "night"
    start_phase(game, "night")
    # 上一夜未使用的13水过期收回；米莉亚的换血目标单独持久保存，直到下次有效换血覆盖。
    game["water"] = {"holders": []}
    game["night"] = {
        "actors": {s["id"]: current(game, s)["id"] for s in game["seats"] if current(game, s)},
        "actions": [],
        "confirmed": [],
        "locked": False,
        "preview": None,
        "reactions": [],
        # 本夜梅露露是否已经放弃复活：主持人推进或30秒警告到点时写入，入口随之关闭。
        "revive_declined": False,
    }
    # 用 card_actionable：傀儡牌由控制它的梅露露代行，不能当「本夜无事可做」自动确认掉。
    sync_night_confirmations(game, events)
    witch_information(game, events)
    notify(game, events, "夜间行动开始，请选择行动后确认；也可放弃并确认。")
    # Everyone else auto-confirming can leave Coco as the only pending actor; nobody
    # would trigger the final confirmation step for her otherwise.
    plugins.emit(game, events, "phase_enter", {"from": previous, "to": "night", "day": game["day"]})
    unlock_coco(game, events)


def target_allowed(game, target_card_id):
    return True


def lock_night(game, events):
    night = game["night"]
    require(not night["locked"], "本夜已经锁定")
    require(set(night["actors"]).issubset(night["confirmed"]), "仍有玩家未确认；可先警告并等待30秒")
    millia.force_swap(game, events)
    night["locked"] = True
    for action in night["actions"]:
        card = game["cards"][action["card_id"]]
        ability = action["ability"]
        action["title"] = f"{action['seat_id']}号 · {NIGHT_ABILITIES[ability][1]}"
        if action.get("resolved"):
            continue
        # 夜间技能都不吃中毒效果骰，锁定后一律视为生效；信息类在下面的分支单独结算。
        action["effective"] = True
        if ability == "witch_scan":
            nanoka.scan_witches(game, events, card)
            continue
        if ability == "arisa_injure":
            arisa.roll_injuries(game, action)
    for action in night["actions"]:
        if action.get("effective"):
            plugins.emit(
                game,
                events,
                "night_action",
                {
                    "seat_id": action["seat_id"],
                    "card_id": action["card_id"],
                    "ability": action["ability"],
                },
            )
    for photo in game["photos"]:
        if photo.get("allowed"):
            actions = [a for a in night["actions"] if a["seat_id"] == photo["target"]]
            notify(game, events, night_text(game, actions), [photo["sender"]], "照片授权的夜间行动")
    annan.publish_rest(game, events)
    previous = game["phase"]
    start_phase(game, "night_review")
    prepare_night_preview(game, events)
    if not game.get("rewound_night"):
        plugins.emit(
            game,
            events,
            "phase_enter",
            {
                "from": previous,
                "to": "night_review",
                "day": game["day"],
            },
        )


def damage_preview(game, attacks, protection=()):
    injured = {c["id"]: c["injured"] for c in game["cards"].values()}
    dead = {}
    guarded_seats = {sid for sid, key in game["half_exits"].items() if key == half_key(game)}
    loved = loved_card_id(game)
    # 被玛格的爱挡下来的攻击：这里只记事实，真正的播报在天亮时发
    # （见 publish_night_passives），预结算期间不发消息——夜里出局一律压到天亮公示。
    love_blocked = []
    for index, attack in enumerate(attacks):
        cid = attack["target_card"]
        if cid not in game["cards"] or not game["cards"][cid]["alive"]:
            continue
        sid = owner(game, cid)["id"]
        if sid in guarded_seats or cid in dead:
            continue
        if cid == loved and attack.get("cause") != "love":
            # 玛格的爱优先级最高：爱人免疫魔女刀、13水、全场攻击、处决等其他一切死亡与负伤。
            # 玛格自己每夜那一发（cause="love"）不在这里短路，落到下面的负伤判定：
            # 第一次只负伤，已有负伤时再次负伤即无条件死亡（规则「免疫所有死亡和其他负伤」）。
            love_blocked.append(cid)
            continue
        if current(game, sid)["id"] != cid and not attack.get("allow_lower"):
            continue
        protected = cid in protection or protection_active(game, game["cards"][cid])
        # attack_index 只给米莉亚替死用来定位「哪一击真的造成了这次出局」，不进公告。
        if (
            attack.get("once_injury")
            or attack.get("injury")
            or (protected and not attack.get("unconditional"))
        ):
            # 负伤没有「只负伤一次、永不升级」的例外：已有负伤时再次负伤无条件死亡。
            if injured[cid]:
                dead[cid] = {**attack, "seat_id": sid, "attack_index": index}
                guarded_seats.add(sid)
            else:
                injured[cid] = True
        else:
            dead[cid] = {**attack, "seat_id": sid, "attack_index": index}
            guarded_seats.add(sid)
    devotion = sherry.devotion(game, dead, guarded_seats)
    if devotion:
        dead["sherry"] = devotion
    return {
        "deaths": list(dead.values()),
        "injured": injured,
        "attacks": deepcopy(attacks),
        "love_blocked": love_blocked,
    }


# 魔女一方的袭击能力：目击的触发条件是「被它指到」，不是「因此出局」。
# 庇护把这一击降级成负伤、玛格的爱免除它、米莉亚替死把致死一击转走，都算被指到。
WITCH_ATTACK_CAUSES = frozenset({"knife", "extra_kill", "massacre"})

# 没有对应夜间技能名的死因，在主持人日志里用的中文备注。
DEATH_CAUSE_LABELS = {"puppet": "傀儡随主人出局"}


def witch_witness_targets(game, attacks):
    """本夜被魔女袭击（魔女刀、额外攻击、全场攻击）指到的席位，每个席位一条。

    必须在米莉亚替死改写攻击目标之前调用：替死把致死一击转到米莉亚牌上，被指到的
    原目标这一侧就再也看不出来了。全场攻击会同时列出上下两张牌，而名单是按席位发
    的，所以按席位去重，victim 取该席当前牌。
    """
    targets, seen = [], set()
    for attack in attacks:
        cid = attack.get("target_card")
        if attack.get("cause") not in WITCH_ATTACK_CAUSES or not cid:
            continue
        card = game["cards"].get(cid)
        if not card or not card["alive"]:
            continue
        s = owner(game, cid)
        if s["id"] in seen:
            continue
        seen.add(s["id"])
        now = current(game, s)
        targets.append(
            {
                "seat_id": s["id"],
                "victim": now["id"] if now else cid,
                "source_card": attack.get("source_card"),
                "cause": attack["cause"],
            }
        )
    return targets


def publish_survivor_witnesses(game, events, preview, killed):
    """被魔女袭击指到但没出局的席位同样要一份目击名单。

    真正出局的席位由普通死亡路径发名单，这里只补「本夜没死」的那些：庇护降级为
    负伤、爱人免疫、米莉亚替死都只改变结算结果，不改变「他被袭击了」这件事。
    名单同样经主持人填写（技能处理后的真凶与穗乃香改名都走原路径）；当事人中毒时
    与死者一样只掷一次信息骰。
    """
    died_cards = {death["target_card"] for death in killed}
    died_seats = {death["seat_id"] for death in killed}
    for target in preview.get("witch_targets", []):
        if target["seat_id"] in died_seats or target["victim"] in died_cards:
            continue
        card = game["cards"][target["victim"]]
        truthful = effect_effective(game, card, "夜间目击名单")
        label = NIGHT_ABILITIES[target["cause"]][1]
        title = (
            f"{target['seat_id']}号夜间被{label}袭击（未出局）："
            f"填写{witness_label(witness_size(game))}（真凶与汉娜优先）"
        )
        if not truthful:
            title += "；本夜当事人中毒、目击信息骰失败，发给他的名单不含真凶"
        pending(
            game,
            "suspects",
            title,
            seat_id=target["seat_id"],
            victim=target["victim"],
            source_card=target.get("source_card"),
            truthful=truthful,
        )


def resolve_intents(game, events, attacks, protection=(), *, night=False, substitute=True):
    """Plugins alter intents, never adjudicated deaths; a later edit gets one recomputation."""
    context = {"attacks": attacks, "protection": list(protection)}
    initial = deepcopy((attacks, list(protection)))
    if night:
        plugins.emit(game, events, "attack_intents", context)
    original = deepcopy((context["attacks"], context["protection"]))

    def calculate():
        raw = context["attacks"]
        guarded = context["protection"]
        witness = witch_witness_targets(game, raw) if night else []
        substituted = millia.substitute(game, raw, guarded, record=False) if substitute else raw
        result = damage_preview(game, substituted, guarded)
        if night:
            result["witch_targets"] = witness
        return result

    preview = calculate()
    context["preview"] = deepcopy(preview)
    plugins.emit(game, events, "post_preview", context)
    if (context["attacks"], context["protection"]) != initial:
        log_event(
            game,
            "system",
            f"规则补丁调整攻击意图：{initial} → {(context['attacks'], context['protection'])}",
        )
    if (context["attacks"], context["protection"]) != original:
        preview = calculate()
    if night and any(a.get("substituted_from") for a in preview["attacks"]):
        game["night"]["reactions"].append("millia")
    return preview


def prepare_night_preview(game, events=None):
    night = game["night"]
    night["reactions"] = [r for r in night["reactions"] if r != "millia"]
    preview, dead = night_damage(game, events if events is not None else [])
    night["preview"] = preview
    # 夜间预结算里希罗死亡时立即回溯到前一天顺序发言，不放主持人待办。
    # 事件队列必须原样传下去：回溯是公开事件，用空列表会把「游戏时间已回溯」
    # 吞掉，玩家只会看到整夜被打回重来（额度却照扣）。只有拿不到队列的
    # REST 入口（api.room_command 的替补接管）才允许传 None。
    if "hiro" in dead:
        hiro.rewind_on_death(game, events if events is not None else [], "night")


def night_damage(game, events=None):
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
        elif ability == "knife" and target:
            attacks.append(
                {"target_card": target, "source_card": action["card_id"], "cause": ability}
            )
        elif ability == "extra_kill" and target:
            attacks.append(hanna.extra_attack(action, target))
        elif ability == "massacre":
            attacks.extend(emma.night_attacks(game, action))
        elif ability == "treasure":
            attacks.extend(emma_treasure.night_attacks(game, action))
        elif ability == "arisa_injure":
            arisa.contribute_attacks(action, attacks)
    marg.contribute_love_attack(game, attacks)
    attacks.extend(night.get("extra_attacks", []))
    # 「被魔女指到就有目击」按意图记账：必须在替死改写目标之前抓一份。
    preview = resolve_intents(
        game, events if events is not None else [], attacks, protection, night=True
    )
    return preview, {death["target_card"] for death in preview["deaths"]}


def eliminate_seat(game, events, seat, notice):
    """整席出局：两张牌直接作废，不触发出局流程（亡语、回溯、证物、疑似凶手等）。

    「质疑失败」是「同一名玩家同一半天最多出局一张牌」的唯一例外：这里一次带走两张，
    但已经出局的牌不再重复记账，也不再为它补写一条 death。
    """
    for card_id in seat["cards"]:
        card = game["cards"][card_id]
        if not card["alive"]:
            continue
        card["alive"] = False
        # 整席出局没有「傀儡当前牌出局」的解除流程，状态必须在这里一并清掉：
        # 留着 puppet/no_ability 会让这张牌被回溯或主持人复活后继续当别人的傀儡。
        release_puppet(card)
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
    """向死者发送疑似凶手名单（三人；汉娜在场时四人），并记录本夜已发目击供复活撤销。"""
    shown = [honoka_role if role == "honoka" else role for role in suspects]
    text = f"{witness_label(len(shown))}：" + "、".join(ROLES[role]["name"] for role in shown)
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


WITNESS_BASE = 3
WITNESS_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}


def witness_size(game):
    """七双目击名单人数：基础三人；汉娜在场（存活且是该席当前牌）时多一人。

    用户批注（A01/A02）：只按汉娜是否在场决定 3 还是 4；梅露露不再必进名单。
    """
    return WITNESS_BASE + hanna.witness_extra(game)


def witness_label(size):
    return f"{WITNESS_CN.get(size, size)}名疑似凶手"


def witness_suspects(game, killer_role):
    """七双目击名单：真凶（技能处理后的显示凶手）+ 在场的汉娜，余位随机补齐。"""
    size = witness_size(game)
    fixed = [role for role in (killer_role, "hanna" if hanna.witness_extra(game) else None) if role]
    suspects = list(dict.fromkeys(fixed))[:size]
    pool = [role for role in ROLES if role not in suspects]
    SystemRandom().shuffle(pool)
    return suspects + pool[: size - len(suspects)]


def false_witness(game, suspects, shown_source):
    """中毒信息失败时发出去的假目击名单：把显示真凶换成一名未入选角色。

    汉娜按规则始终在名单里，真凶就是汉娜时给不出不含真凶的名单，只能原样保留。
    """
    if not shown_source or shown_source == "hanna" or shown_source not in suspects:
        return list(suspects)
    pool = [role for role in ROLES if role not in suspects]
    if not pool:
        return list(suspects)
    SystemRandom().shuffle(pool)
    return [pool[0] if role == shown_source else role for role in suspects]


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
        # 疑凶目击是发给死者的信息：死者中毒时同样只掷一次信息骰，各1/2生效；
        # 必须在判定出局前掷，否则出局后艾玛邻接毒源会随当前牌变化而失效。
        witness_truthful = True
        if game["half"] == "night":
            witness_truthful = effect_effective(game, card, "夜间目击名单")
        card["alive"] = False
        game["half_exits"][s["id"]] = half_key(game)
        record = {
            "id": uid(),
            "day": game["day"],
            "half": game["half"],
            # attack_index 只服务于替死定位，不进对局记录与主持人视图。
            **{k: v for k, v in deepcopy(death).items() if k != "attack_index"},
        }
        game["deaths"].append(record)
        killed.append(record)
        source = death.get("source_card")
        if source:
            game["cards"][source]["states"].setdefault("kills", []).append(
                {"card_id": cid, "day": game["day"]}
            )
        noah.publish_footprints(game, events, death)
        hidden = bool(death.get("hide_cause"))
        suffixed = death.get("cause") == "water" and not hidden
        # 公告里的角色名取**公开头像**，不取真实牌：示人的穗乃香出局时不能顺着真实牌
        # 把她的示人身份说破，与同一时刻下发的死亡卡片（state.death_card_entry）同一口径。
        shown_role = before["avatar_role_id"] or cid
        shown_name = ROLES.get(shown_role, {}).get("name", shown_role)
        notice = (
            f"{s['id']}号 · {shown_name}被13水毒杀。"
            if suffixed
            else f"{s['id']}号 · {shown_name}一张角色牌出局。"
        )
        record["notice"] = notice
        # 非夜间技能造成的死亡（处决、质疑、傀儡随主人出局等）没有技能名，按死因备注。
        cause_label = (
            DEATH_CAUSE_LABELS.get(death.get("cause"))
            or NIGHT_ABILITIES.get(death.get("cause"), (None, death.get("cause") or ""))[1]
        )
        src = death.get("source_card")
        src_label = ROLES.get(src, {}).get("name", src) if src else ""
        detail = (
            f"（{cause_label}" + (f"·{src_label}" if src_label else "") + ")" if cause_label else ""
        )
        log_event(game, "death", f"{s['id']}号的{ROLES[cid]['name']}出局{detail}")
        # 角色卡死亡卡片的一条：只带已经公开的信息（公开头像、展示名、是否13水），
        # 真实牌 id 与死因都不进载荷（见 state.death_card_entry）。
        entry = death_card_entry(game, s, before, suffixed)
        if game["half"] == "night":
            # 夜间出局连同头像一起压到第二天白天再公示，夜间阶段不泄露
            game["queued_notices"].append(notice)
            game["queued_reveals"].append(before)
            game.setdefault("queued_deaths", []).append(entry)
            if suffixed:
                # 未隐藏的13水死亡：直接构造并随机排序疑凶目击，无需主持人待办。
                # 替罪凶手与主持人填写路径口径一致：名单按「显示凶手」取名单位。
                shown = game["cards"][src]["states"].get("display_killer", src) if src else None
                suspects = witness_suspects(game, shown)
                if not witness_truthful:
                    suspects = false_witness(game, suspects, shown)
                witness_item = {"seat_id": s["id"], "victim": cid, "death_id": record["id"]}
                honoka.queue_witness(game, events, witness_item, suspects)
            else:
                title = (
                    f"{s['id']}号夜间死者："
                    f"填写{witness_label(witness_size(game))}（真凶与汉娜优先）"
                )
                if not witness_truthful:
                    title += "；本夜死者中毒、目击信息骰失败，发给他的名单不含真凶"
                pending(
                    game,
                    "suspects",
                    title,
                    seat_id=s["id"],
                    death_id=record["id"],
                    victim=cid,
                    source_card=source,
                    truthful=witness_truthful,
                )
        else:
            notify(
                game,
                events,
                notice,
                alert=True,
                payload=death_card_payload(game, [entry]),
                reference_title="出局公告",
            )
            # 白天死亡当场公示，下层牌立即登场并取得本阶段的行动。
            lower = current(game, s)
            if lower:
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
        if release_puppet(card):
            # 傀儡当前牌出局：控制关系解除；该席下层牌仍存活则本人重新回到游戏。
            if current(game, s):
                notify(
                    game,
                    events,
                    "你已重新回到游戏，恢复普通玩家权限。",
                    [s["id"]],
                    "傀儡解除",
                )
        plugins.emit(game, events, "death_committed", {"death": record, "card_id": cid})
    if game["half"] == "night":
        # 被魔女袭击指到却没出局的席位同样要有目击：目击看的是「被指到」。
        publish_survivor_witnesses(game, events, preview, killed)
    wipe_massacred_seats(game, events, killed)
    # 死亡落实后重算阵营胜负；艾玛单胜在进入 night_results 后判定，实际死亡人数不限。
    check_winner(game)
    plugins.emit(game, events, "post_resolve", {"deaths": tuple(killed)})


def wipe_massacred_seats(game, events, killed):
    """全场攻击是「杀死所有其他角色」：被它打下当前牌的席位，另一张牌一并作废。

    用户 2026-09-27 追加：这是「同一半天同一人最多出一张牌」的第二条例外（第一条是
    质疑失败整席出局）。这里只把剩下的牌直接置为出局、**不补 death 记录**——同一玩家
    一夜只该有一条死亡公告、一份目击与一个证物，补记录会把这些都翻倍。
    被庇护、玛格的爱或米莉亚替死挡下当前牌的席位不算被打下场，照常两张牌都在。
    """
    for death in killed:
        if death.get("cause") != "massacre":
            continue
        s = seat(game, death["seat_id"])
        for cid in s["cards"]:
            card = game["cards"][cid]
            if not card["alive"]:
                continue
            card["alive"] = False
            release_puppet(card)
            log_event(game, "death", f"{s['id']}号的{ROLES[cid]['name']}被全场攻击一并打下场")
    return killed


def passive_seat_label(game, card_id):
    row = owner(game, card_id) if card_id in game["cards"] else None
    return f"{row['id']}号" if row else ""


def love_left_target(game):
    """被爱的那张牌是否已经出局（即玛格是否已经转爱自己）。

    与 :func:`love_is_self` 同源，但**不看**「爱是否已经进入生效期」：声明当天那张牌
    就出局时也要告诉她。``active_love`` 的当天限制是给伤害结算用的，不是给通知用的。
    """
    love = game.get("marg_love")
    if not love:
        return False
    cid = love.get("card_id")
    if not cid:
        return current(game, seat(game, love["seat_id"])) is None
    card = game["cards"].get(cid)
    return card is None or not card["alive"]


def publish_love_self(game, events):
    """被爱的那张牌出局后玛格转爱自己：只发一次，私密发给玛格本人。

    ``marg_love`` 属于对局状态，希罗回溯会把它一起还原，所以「已经通知过」的标记
    也跟着时间线走：回溯撤销那次死亡时，转爱自己的提示自然也不再成立；本人重新宣布
    爱人时会整份覆盖 ``marg_love``，标记随之清空。
    """
    love = game.get("marg_love")
    if not love or love.get("self_notified") or not present(game, "marg"):
        return
    if not love_left_target(game):
        return
    love["self_notified"] = True
    effect = "被爱的那张牌已经出局，你转爱自己：此后由你自己享受这份庇护。"
    notify(
        game,
        events,
        effect,
        [owner(game, "marg")["id"]],
        "转爱自己",
        payload=passive_card_payload(game, "love_self", effect),
    )


def publish_night_passives(game, events):
    """天亮时补发夜间被动技能的播报卡片。

    替死与爱人庇护都发生在夜间预结算里，但公开口径是「夜间出局一律压到天亮公示」，
    所以这里等天亮、死亡公告一起发，夜间阶段不发任何提示。被梅露露复活的死亡已经
    不在 ``game["deaths"]`` 里，因此按最终状态推导即可，撤销过的一次自然不会补发。
    """
    for death in game["deaths"]:
        if death.get("day") != game["day"] or death.get("half") != "night":
            continue
        millia.publish_substitute(game, events, death.get("substituted_from"))
    publish_love_blocked(game, events, (game.get("night") or {}).get("love_blocked"))
    publish_love_self(game, events)


def publish_love_blocked(game, events, card_ids):
    """爱人庇护挡住了攻击：只告诉玛格本人「爱人被袭击但没有出局」。

    被爱的牌是私密情报（爱人与移情的对象不在 PUBLIC_TARGET_ABILITIES 里），
    因此这条卡片只发给玛格与主持人；其他玩家只看得到「没有人出局」。
    """
    blocked = sorted(set(card_ids or []))
    names = [name for name in (passive_seat_label(game, cid) for cid in blocked) if name]
    if not names or not present(game, "marg"):
        return
    effect = f"你的爱人（{'、'.join(names)}）被袭击，庇护已生效，没有出局。"
    notify(
        game,
        events,
        effect,
        [owner(game, "marg")["id"]],
        "爱人庇护",
        payload=passive_card_payload(game, "love", effect),
    )


def publish_day_passives(game, events, preview):
    """白天伤害结算后立即补发被动技能的播报卡片。

    白天出局当场公示，所以替死与爱人庇护不需要再压时间；这里读的是刚刚结算过的
    那一份 preview，与死亡公告同一时刻、同一份事实。
    """
    for death in preview.get("deaths") or []:
        millia.publish_substitute(game, events, death.get("substituted_from"))
    publish_love_blocked(game, events, preview.get("love_blocked"))
    publish_love_self(game, events)


def revive(game, events, card_id, puppet=None):
    card = game["cards"][card_id]
    require(not card["alive"], "该牌尚未出局")
    card["alive"] = True
    card["injured"] = False
    if puppet:
        card["states"]["puppet"] = puppet
        card["states"]["no_ability"] = True
    else:
        # 回溯或主持人复活的牌一律不是傀儡：留着旧的 puppet/no_ability 会让它带着
        # 「继续被控制」或「永久无技能」的残留状态重新登场。
        release_puppet(card)
    owner_seat = owner(game, card_id)
    now = current(game, owner_seat)
    if now:
        owner_seat["avatar_role_id"] = now["role_id"]
    # 复活不单独播报：它与「当夜死亡通告被撤销 → 天亮判为平安夜」自相矛盾，还会把
    # 「当夜有人被杀、魔女用过复活」这两件事一起泄露出去。撤销本身照常发生。
    check_winner(game)
